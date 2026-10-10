"""Façade de services du module Inventory.

Le stock n'a qu'une **table** d'entrée, `inventory_movements`, et quatre portes vers
elle : `record_movement` pour une saisie humaine, `record_sale_out`,
`reverse_sale_out` et `record_customer_return_in` pour les flux de vente. Les trois
dernières existent parce que `sale_out` et `customer_return_in` ne sont pas des types
saisissables — personne ne « saisit » une sortie de vente, elle est la conséquence
d'une confirmation. Sales dit ce qui est vendu ou rendu ; c'est Inventory qui compose
le mouvement, ici et nulle part ailleurs.

Ce que ce module ne fait pas, et ne fera jamais :

* écrire `product_stock` — c'est le trigger `t20_inv_apply` qui la maintient (§ 5.6) ;
* recalculer un CMP en Python — la seule formule est `cmp_next_avg`, en base (§ 5.7) ;
* modifier ou supprimer un mouvement — le journal est append-only, on l'annule.

Son vrai travail est ailleurs : traduire les refus de PostgreSQL en erreurs métier
nommées, écrire l'audit critique des ajustements manuels, et poser l'événement
`stock.updated` dans la transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core import clock, money
from app.core.audit import AuditAction, audit_critical
from app.core.errors import (
    BusinessRuleError,
    NotFoundError,
    ValidationFailedError,
    constraint_name,
    sqlstate,
)
from app.core.events.outbox import emit
from app.core.events.types import EventType
from app.core.tenancy import TenantContext
from app.modules.categories import service as categories_service
from app.modules.finance import service as finance_service
from app.modules.finance.schemas import AllocationInput, DebtCreate, PaymentCreate
from app.modules.inventory.events import AGGREGATE_TYPE, stock_updated_payload
from app.modules.inventory.models import InventoryMovement, ProductStock
from app.modules.inventory.repository import (
    InventoryMovementRepository,
    ProductStockRepository,
    StockHistoryRepository,
)
from app.modules.inventory.schemas import (
    CORRECTION_TYPES,
    MANUAL_MOVEMENT_TYPES,
    DeliveryCreate,
    DeliveryLineRead,
    DeliveryRead,
    MovementCreate,
    MovementRead,
    NewProductCreate,
    NewProductRead,
    StockLine,
    StockRebuildLine,
    StockSummary,
)
from app.modules.products import service as products_service
from app.modules.products.schemas import ProductRead, ProductSummary

# --------------------------------------------------------------- erreurs métier
# Une classe par règle, avec son code stable en anglais et son message en français.


class InsufficientStockError(BusinessRuleError):
    code = "insufficient_stock"
    default_message = "Stock insuffisant : cette sortie rendrait la quantité négative."


class ProductNotStockTrackedError(BusinessRuleError):
    code = "product_not_stock_tracked"
    default_message = "Ce produit n'est pas suivi en stock : aucun mouvement n'est possible."


class MovementBackdatedTooFarError(BusinessRuleError):
    code = "movement_backdated_too_far"
    default_message = (
        "Date trop ancienne : un mouvement ne peut pas précéder de plus de 48 heures "
        "le dernier mouvement du produit."
    )


class MovementInFutureError(BusinessRuleError):
    code = "movement_in_future"
    default_message = "Date invalide : un mouvement de stock ne peut pas être daté dans le futur."


class AlreadyReversedError(BusinessRuleError):
    code = "already_reversed"
    default_message = "Ce mouvement a déjà été annulé."


class NotReversibleError(BusinessRuleError):
    code = "movement_not_reversible"
    default_message = "Une annulation ne s'annule pas : corriger par un ajustement."


class FlowMovementNotReversibleError(BusinessRuleError):
    """Un mouvement né d'une vente ou d'un retour ne se corrige pas depuis le stock."""

    code = "movement_not_reversible"
    default_message = (
        "Ce mouvement vient d'une vente ou d'un retour client : "
        "corrigez-le en annulant la vente ou en enregistrant un retour."
    )


class DuplicateMovementError(BusinessRuleError):
    code = "duplicate_movement"
    default_message = "Ce mouvement a déjà été enregistré avec la même clé d'idempotence."


class InitialStockAlreadySetError(BusinessRuleError):
    code = "initial_stock_already_set"
    default_message = "Le stock initial de ce produit a déjà été saisi."


class UnitCostRequiredError(BusinessRuleError):
    code = "unit_cost_required"
    default_message = (
        "Coût unitaire obligatoire : le produit n'a pas encore de coût moyen à reprendre."
    )


#: SQLSTATE applicatifs levés par les triggers de la migration 0004 (ADR 0018).
_TRIGGER_ERRORS: dict[str, type[BusinessRuleError]] = {
    "CG010": MovementBackdatedTooFarError,
    "CG011": MovementInFutureError,
    "CG020": InsufficientStockError,
    "CG021": ProductNotStockTrackedError,
}
_UNIQUE_VIOLATION = "23505"

#: `ref_type` des mouvements nés d'une ligne de vente (§ 5.1 étape 4).
SALE_ITEM_REF = "sale_item"

#: `ref_type` des mouvements nés d'une ligne de retour client (§ 5.3 étape 3).
SALE_RETURN_ITEM_REF = "sale_return_item"

_REBUILD_SQL = text("SELECT * FROM rebuild_product_stock(:company_id)")


def _translate(exc: DBAPIError, *, details: dict[str, Any]) -> BusinessRuleError | None:
    """Traduit un refus de PostgreSQL en erreur métier, ou rend None.

    Le SQLSTATE et le nom de contrainte sont stables ; le texte du message ne l'est
    pas (ADR 0014). Rien d'autre n'est inspecté.
    """
    state = sqlstate(exc)
    trigger_error = _TRIGGER_ERRORS.get(state or "")
    if trigger_error is not None:
        return trigger_error(details=details)

    if state == _UNIQUE_VIOLATION:
        name = constraint_name(exc)
        if name == "inv_reversal_uq":
            return AlreadyReversedError(details=details)
        if name == "inv_ref_idempotence":
            if details.get("ref_type") == "initial":
                return InitialStockAlreadySetError(details=details)
            return DuplicateMovementError(details=details)
    return None


# ------------------------------------------------------------------- lectures


def list_movements(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    product_id: UUID | None = None,
    movement_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[Sequence[InventoryMovement], int]:
    """Page du journal, du plus récent au plus ancien."""
    repository = InventoryMovementRepository(session, ctx)
    filters: dict[str, Any] = {
        "product_id": product_id,
        "movement_type": movement_type,
        "date_from": date_from,
        "date_to": date_to,
    }
    return (
        repository.page_filtered(page=page, page_size=page_size, **filters),
        repository.count_filtered(**filters),
    )


def net_sold(
    session: Session, ctx: TenantContext, product_id: UUID, *, since: datetime, until: datetime
) -> Decimal:
    """Quantité vendue nette d'un article sur une période (« Vendu ce mois »)."""
    return InventoryMovementRepository(session, ctx).net_sold(product_id, since=since, until=until)


def get_movement(session: Session, ctx: TenantContext, movement_id: UUID) -> InventoryMovement:
    """Mouvement du tenant courant. Celui d'une autre entreprise donne 404."""
    movement = InventoryMovementRepository(session, ctx).get(movement_id)
    if movement is None:
        raise NotFoundError("Mouvement de stock introuvable.")
    return movement


def _status(qty_on_hand: Decimal, reorder_point: Decimal | None) -> str:
    """Statut d'un article : rupture, seuil atteint, ou rien à signaler."""
    if qty_on_hand == 0:
        return "out"
    if reorder_point is not None and qty_on_hand <= reorder_point:
        return "low"
    return "ok"


#: Une livraison rattache ses entrées à la dette fournisseur qui la porte (révision 0017).
DELIVERY_REF_TYPE = "supplier_debt"

#: Fenêtre du niveau d'un article : son stock rapporté au plus haut des 90 derniers jours.
LEVEL_WINDOW_DAYS = 90
_STATUS_ORDER = {"out": 0, "low": 1, "ok": 2}


class _StockRow(NamedTuple):
    """Une ligne de la vue Stock : la projection, ou un article encore jamais entré."""

    product_id: UUID
    qty_on_hand: Decimal
    avg_cost: Decimal
    stock_value: Decimal
    last_movement_at: datetime | None


def _stock_rows(
    session: Session, ctx: TenantContext, product_ids: Sequence[UUID] | None
) -> tuple[list[_StockRow], dict[UUID, ProductSummary]]:
    """Lignes de stock et fiches. Sans lot d'articles, les articles actifs qui n'ont
    encore aucun mouvement (créés sans stock, ou non suivis) y figurent à zéro : l'écran
    Stock les montre aussi (ADR 0071)."""
    repository = ProductStockRepository(session, ctx)
    stored = list(repository.many(list(product_ids)).values()) if product_ids else repository.all()
    rows = [
        _StockRow(
            row.product_id, row.qty_on_hand, row.avg_cost, row.stock_value, row.last_movement_at
        )
        for row in stored
    ]
    summaries = products_service.get_summaries(session, ctx, [row.product_id for row in rows])
    if not product_ids:
        active = products_service.active_summaries(session, ctx)
        known = {row.product_id for row in rows}
        for product_id, summary in active.items():
            if product_id not in known:
                rows.append(_StockRow(product_id, Decimal("0"), Decimal("0"), Decimal("0"), None))
                summaries[product_id] = summary
    return rows, summaries


def _row_status(row: _StockRow, summary: ProductSummary) -> str:
    """Un article non suivi n'est jamais « épuisé » : il n'a pas de stock à compter."""
    if not summary.is_stock_tracked:
        return "ok"
    return _status(row.qty_on_hand, summary.reorder_point)


def _level(qty: Decimal, highest: Decimal | None) -> Decimal:
    """Part du plus haut stock récent qui reste (0 à 1), au centième."""
    peak = qty if highest is None else max(highest, qty)
    if peak <= 0:
        return Decimal("0.00")
    return (qty / peak).quantize(Decimal("0.01"))


def get_stock(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    product_ids: Sequence[UUID] | None = None,
    status: str | None = None,
    category_id: UUID | None = None,
    search: str | None = None,
) -> tuple[list[StockLine], int]:
    """Stock valorisé, joint aux fiches produit, filtré et trié (ADR 0012, ADR 0071).

    Inventory (bande C) lit Products (bande B) **par sa façade**, jamais par son modèle.
    Épuisés d'abord, puis bientôt épuisés, puis les autres, par nom : c'est ce que le
    gérant cherche. `product_ids` restreint la liste à un lot d'articles (saisie d'une
    vente, ADR 0050) ; `status`, `category_id` et `search` sont les puces et la
    recherche de l'écran Stock. Chaque ligne donne son prix de vente et son niveau, le
    stock rapporté au plus haut des 90 derniers jours.
    """
    stock_repository = ProductStockRepository(session, ctx)
    rows, summaries = _stock_rows(session, ctx, product_ids)
    matching = None if not search else products_service.ids_matching(session, ctx, search)
    selected: list[tuple[_StockRow, ProductSummary, str]] = []
    for row in rows:
        summary = summaries.get(row.product_id)
        if summary is None:
            # Produit supprimé logiquement : sa projection survit (le journal aussi),
            # mais la fiche n'est plus lisible. On ne devine rien, on n'affiche rien.
            continue
        state = _row_status(row, summary)
        if status is not None and state != status:
            continue
        if category_id is not None and summary.category_id != category_id:
            continue
        if matching is not None and row.product_id not in matching:
            continue
        selected.append((row, summary, state))
    selected.sort(key=lambda item: (_STATUS_ORDER[item[2]], item[1].name.casefold()))
    shown = selected[(page - 1) * page_size : page * page_size]

    shown_ids = [row.product_id for row, _, _ in shown]
    category_names = categories_service.get_names(
        session,
        ctx,
        [summary.category_id for _, summary, _ in shown if summary.category_id is not None],
    )
    prices = products_service.current_unit_prices(session, ctx, shown_ids)
    since = clock.now() - timedelta(days=LEVEL_WINDOW_DAYS)
    highest = stock_repository.highest_on_hand_since(shown_ids, since)

    lines = [
        StockLine(
            product_id=row.product_id,
            sku=summary.sku,
            name=summary.name,
            unit=summary.unit,
            category_id=summary.category_id,
            category_name=(
                None if summary.category_id is None else category_names.get(summary.category_id)
            ),
            qty_on_hand=row.qty_on_hand,
            avg_cost=row.avg_cost,
            stock_value=row.stock_value,
            reorder_point=summary.reorder_point,
            status=state,
            last_movement_at=row.last_movement_at,
            unit_price=prices.get(row.product_id),
            level=_level(row.qty_on_hand, highest.get(row.product_id)),
            is_stock_tracked=summary.is_stock_tracked,
        )
        for row, summary, state in shown
    ]
    return lines, len(selected)


def stock_summary(session: Session, ctx: TenantContext) -> StockSummary:
    """En tête de l'écran Stock : articles, valeur au prix d'achat, alertes (ADR 0071)."""
    rows, summaries = _stock_rows(session, ctx, None)
    live = [(row, summaries[row.product_id]) for row in rows if row.product_id in summaries]
    states = [_row_status(row, summary) for row, summary in live]
    return StockSummary(
        product_count=len(live),
        stock_value=money.amount(sum((row.stock_value for row, _ in live), Decimal("0"))),
        low_count=states.count("low"),
        out_count=states.count("out"),
    )


# ------------------------------------------------------------------- écritures


def _reference(
    payload: MovementCreate, idempotency_key: UUID | None
) -> tuple[str | None, UUID | None]:
    """Couple `(ref_type, ref_id)` d'un mouvement manuel.

    `inv_ref_pair` impose les deux ou aucun. Deux usages, une seule mécanique —
    l'index partiel `inv_ref_idempotence` :

    * `initial` porte `ref_id = product_id`, ce qui rend **un seul** stock initial
      par produit possible, garanti en base plutôt que par un contrôle applicatif ;
    * un mouvement manuel accompagné d'une clé d'idempotence la porte telle quelle,
      ce qui rejette un double envoi du formulaire.
    """
    if payload.type == "initial":
        return "initial", payload.product_id
    if idempotency_key is not None:
        return "manual", idempotency_key
    return None, None


def _entry_unit_cost(payload: MovementCreate, current: ProductStock | None) -> Decimal:
    """Coût unitaire à inscrire sur le mouvement.

    Une sortie part à zéro : `t20_inv_apply` l'estampille au CMP applicable, et
    c'est lui qui fait foi (§ 5.6). Une entrée saisie porte son coût d'acquisition.
    Un ajustement positif sans coût reprend le CMP courant, pour ne pas déformer la
    valorisation en retrouvant de la marchandise déjà valorisée (ADR 0016).
    """
    if payload.unit_cost is not None:
        return payload.unit_cost
    if payload.qty_delta < 0:
        return Decimal("0")

    current_avg = Decimal("0") if current is None else current.avg_cost
    if current_avg == 0:
        raise UnitCostRequiredError(details={"product_id": str(payload.product_id)})
    return current_avg


def record_movement(
    session: Session,
    ctx: TenantContext,
    payload: MovementCreate,
    *,
    idempotency_key: UUID | None = None,
    reference: tuple[str, UUID] | None = None,
    ip_address: str | None = None,
) -> InventoryMovement:
    """Écrit un mouvement, et avec lui le stock, l'audit et l'événement.

    Point d'entrée unique du stock : tout passe par ici, y compris les sorties de
    vente à partir de la phase 05. `reference` rattache le mouvement à la pièce qui
    l'a fait naître (la dette d'une livraison, ADR 0071).
    """
    if not products_service.is_stock_tracked(session, ctx, payload.product_id):
        # Le trigger `CG021` reste l'autorité ; ce contrôle rend la main plus tôt,
        # avec un message qui nomme le produit.
        raise ProductNotStockTrackedError(details={"product_id": str(payload.product_id)})

    stock_repository = ProductStockRepository(session, ctx)
    current = stock_repository.get(payload.product_id)
    # Capturés avant le `flush` risqué : après un rejet, la transaction est morte et
    # relire un attribut expiré échouerait à son tour (ADR 0010).
    available = Decimal("0") if current is None else current.qty_on_hand
    ref_type, ref_id = reference or _reference(payload, idempotency_key)

    entry = InventoryMovement(
        company_id=ctx.company_id,
        product_id=payload.product_id,
        type=payload.movement_type,
        qty_delta=payload.qty_delta,
        unit_cost=_entry_unit_cost(payload, current),
        ref_type=ref_type,
        ref_id=ref_id,
        supplier_id=payload.supplier_id,
        note=payload.note,
        reason_code=payload.reason_code,
        created_by=ctx.user_id,
    )
    if payload.occurred_at is not None:
        # Sans date saisie, on laisse le `DEFAULT now()` de PostgreSQL : affecter
        # `None` enverrait un NULL sur une colonne qui n'en accepte pas.
        entry.occurred_at = payload.occurred_at
    movement = InventoryMovementRepository(session, ctx).add(entry)
    _flush(
        session,
        movement,
        details={
            "product_id": str(payload.product_id),
            "ref_type": ref_type,
            "available": str(available),
        },
    )

    if payload.type in CORRECTION_TYPES:
        # Seule écriture de stock qui ne vient d'aucun flux métier : audit critique,
        # dans la transaction (liste des opérations, Architecture technique).
        audit_critical(
            session,
            ctx,
            action=AuditAction.INSERT,
            entity_table="inventory_movements",
            entity_id=movement.id,
            after=_audited(movement),
            ip_address=ip_address,
        )

    _emit_stock_updated(session, ctx, movement)
    return movement


def create_product_with_stock(
    session: Session,
    ctx: TenantContext,
    payload: NewProductCreate,
    *,
    ip_address: str | None = None,
) -> NewProductRead:
    """Crée l'article par la façade de Products, puis son stock d'ouverture (ADR 0066).

    Une seule transaction : si le mouvement est refusé, l'article ne reste pas.
    """
    product, price = products_service.create_product(
        session, ctx, payload.product(), ip_address=ip_address
    )
    movement = None
    if payload.opening_qty > 0:
        movement = record_movement(
            session,
            ctx,
            MovementCreate(
                product_id=product.id,
                type="initial",
                qty_delta=payload.opening_qty,
                unit_cost=payload.cost_price,
            ),
            ip_address=ip_address,
        )
    return NewProductRead(
        product=ProductRead.build(product, price),
        opening_movement=None if movement is None else MovementRead.model_validate(movement),
    )


class DeliveryPaymentError(ValidationFailedError):
    """« Une partie » qui n'en est pas une : rien, ou le total ou plus.

    422 : la demande se contredit (le total se calcule sur ses propres lignes).
    """

    code = "invalid_delivery_payment"
    default_message = "Le montant payé doit être plus que 0 et moins que le total."


class EmptyDeliveryError(ValidationFailedError):
    code = "empty_delivery"
    default_message = "Une livraison sans montant ne s'enregistre pas : indiquez les prix d'achat."


def receive_delivery(
    session: Session,
    ctx: TenantContext,
    payload: DeliveryCreate,
    *,
    ip_address: str | None = None,
) -> DeliveryRead:
    """Reçoit une livraison fournisseur (écran 11, ADR 0071), tout ou rien.

    1. La dette fournisseur du total s'ouvre, avec son échéance : Finance vérifie le
       fournisseur (404 s'il n'est pas de l'entreprise) et audite la dette.
    2. Chaque article entre en stock (`purchase_in`, au coût tapé : le CMP se recalcule),
       rattaché à la dette par `ref_type = 'supplier_debt'`.
    3. Si l'on paie tout ou une partie, le décaissement est lettré sur la dette.

    Une seule transaction : un refus à n'importe quelle étape n'en laisse aucune trace.
    Inventory appelle Finance par sa façade, comme la confirmation d'une vente.
    """
    total = money.amount(sum((line.qty * line.unit_cost for line in payload.lines), Decimal("0")))
    if total <= 0:
        raise EmptyDeliveryError(details={"total": str(total)})
    paid = {
        "now": total,
        "later": Decimal("0"),
        "part": payload.paid_amount or Decimal("0"),
    }[payload.payment_mode]
    if payload.payment_mode == "part" and not Decimal("0") < paid < total:
        raise DeliveryPaymentError(details={"paid_amount": str(paid), "total": str(total)})

    debt = finance_service.create_debt(
        session,
        ctx,
        DebtCreate(
            party_type="supplier",
            principal=total,
            supplier_id=payload.supplier_id,
            due_date=None if payload.payment_mode == "now" else payload.due_date,
        ),
        ip_address=ip_address,
    )
    lines: list[DeliveryLineRead] = []
    for line in payload.lines:
        movement = record_movement(
            session,
            ctx,
            MovementCreate(
                product_id=line.product_id,
                type="purchase_in",
                qty_delta=line.qty,
                unit_cost=line.unit_cost,
                supplier_id=payload.supplier_id,
            ),
            reference=(DELIVERY_REF_TYPE, debt.id),
            ip_address=ip_address,
        )
        lines.append(
            DeliveryLineRead(
                product_id=line.product_id,
                movement_id=movement.id,
                qty=line.qty,
                unit_cost=line.unit_cost,
            )
        )
    payment = None
    if paid > 0:
        payment = finance_service.record_payment(
            session,
            ctx,
            PaymentCreate(
                direction="outflow",
                method=payload.method,
                amount=paid,
                allocations=[AllocationInput(debt_id=debt.id, amount=paid)],
            ),
            ip_address=ip_address,
        )
    return DeliveryRead(
        debt_id=debt.id,
        supplier_id=payload.supplier_id,
        payment_id=None if payment is None else payment.id,
        total=total,
        paid=paid,
        balance=total - paid,
        due_date=debt.due_date,
        lines=lines,
    )


def reverse_movement(
    session: Session,
    ctx: TenantContext,
    movement_id: UUID,
    *,
    ip_address: str | None = None,
) -> InventoryMovement:
    """Annule un mouvement par son inverse exact.

    Le journal ne se corrige pas : une erreur de saisie s'efface en ajoutant la
    ligne qui la compense, et qui la désigne. `inv_reversal_uq` garantit qu'un
    mouvement n'est annulé qu'une fois, `t10_inv_check_reversal` que l'inverse
    porte bien le même produit et la quantité opposée.
    """
    origin = get_movement(session, ctx, movement_id)
    if origin.type not in MANUAL_MOVEMENT_TYPES:
        # Inverser une sortie de vente remettrait l'article en stock sous une vente
        # toujours confirmée : les flux se corrigent par leur propre cas d'usage
        # (annulation, retour), qui passe par `reverse_sale_out` (ADR 0017, complément).
        raise FlowMovementNotReversibleError(
            details={"movement_id": str(origin.id), "type": origin.type}
        )
    reversal = _write_reversal(session, ctx, origin)

    audit_critical(
        session,
        ctx,
        action=AuditAction.CANCEL,
        entity_table="inventory_movements",
        entity_id=origin.id,
        before=_audited(origin),
        after=_audited(reversal),
        ip_address=ip_address,
    )
    return reversal


def record_sale_out(
    session: Session,
    ctx: TenantContext,
    *,
    product_id: UUID,
    qty: Decimal,
    sale_item_id: UUID,
) -> InventoryMovement:
    """Sortie de stock d'une ligne de vente confirmée (§ 5.1 étape 4).

    `qty` est la quantité **vendue**, positive : c'est Inventory qui en fait un
    `qty_delta` négatif, pour que Sales n'ait jamais à connaître la convention de
    signe du journal.

    Le `unit_cost` part à zéro et revient estampillé au CMP par `t20_inv_apply` —
    c'est lui que Sales recopiera dans `sale_items.unit_cost`, le COGS historique
    de la ligne. Le couple `('sale_item', sale_item_id)` rend l'opération
    idempotente en base : `inv_ref_idempotence` refuse une seconde sortie pour la
    même ligne (T17).

    La date reste le `DEFAULT now()` de PostgreSQL : la marchandise part au moment
    de la confirmation, pas à la date de la vente, qu'un brouillon peut porter
    depuis plusieurs jours — et que la fenêtre d'antidatage refuserait (ADR 0015).
    """
    if not products_service.is_stock_tracked(session, ctx, product_id):
        # Le trigger `CG021` reste l'autorité ; ce contrôle rend la main plus tôt.
        raise ProductNotStockTrackedError(details={"product_id": str(product_id)})

    stock_repository = ProductStockRepository(session, ctx)
    current = stock_repository.get(product_id)
    # Capturé avant le `flush` risqué : après un rejet, la transaction est morte
    # et relire un attribut expiré échouerait à son tour (ADR 0010).
    available = Decimal("0") if current is None else current.qty_on_hand

    movement = InventoryMovementRepository(session, ctx).add(
        InventoryMovement(
            company_id=ctx.company_id,
            product_id=product_id,
            type="sale_out",
            qty_delta=-qty,
            unit_cost=Decimal("0"),
            ref_type=SALE_ITEM_REF,
            ref_id=sale_item_id,
            created_by=ctx.user_id,
        )
    )
    _flush(
        session,
        movement,
        details={
            "product_id": str(product_id),
            "ref_type": SALE_ITEM_REF,
            "requested": str(qty),
            "available": str(available),
        },
    )
    # Pas d'audit critique : une sortie de vente n'est pas une écriture de stock
    # isolée, c'est une conséquence. La confirmation, elle, est auditée par Sales.
    _emit_stock_updated(session, ctx, movement)
    return movement


def record_customer_return_in(
    session: Session,
    ctx: TenantContext,
    *,
    product_id: UUID,
    qty: Decimal,
    unit_cost: Decimal,
    return_item_id: UUID,
) -> InventoryMovement:
    """Remet en stock la marchandise d'une ligne de retour (§ 5.3 étape 3).

    Deux choses distinguent cette entrée de l'inverse écrit par `reverse_sale_out`,
    et elles ne sont pas des détails :

    * **aucun `reversal_of_movement_id`**. Un retour est un fait métier autonome, pas
      l'annulation d'un mouvement. Le client a gardé la marchandise, l'a utilisée
      peut-être, puis l'a rendue : la sortie de vente a bien eu lieu, et le journal
      doit continuer de la montrer. C'est aussi ce qui rend possibles trois retours
      partiels sur une même ligne, là où `inv_reversal_uq` n'en autorise qu'un ;
    * **`unit_cost` est fourni**, et c'est celui de la ligne de vente. La marchandise
      revient au coût auquel elle est sortie, pas au CMP du jour (T19) : le COGS
      historique reste exactement compensé, et une variation du CMP entre la vente et
      le retour ne fabrique ni profit ni perte. Conséquence assumée du § 5.3 : cette
      entrée pèse ensuite sur le CMP courant comme n'importe quelle autre.

    Le couple `('sale_return_item', return_item_id)` rend l'opération idempotente en
    base par `inv_ref_idempotence`. La date reste le `DEFAULT now()` : la marchandise
    rentre quand on la reçoit, pas à la date métier du retour, qu'un gérant peut
    antidater et que la fenêtre de l'ADR 0015 refuserait.
    """
    movement = InventoryMovementRepository(session, ctx).add(
        InventoryMovement(
            company_id=ctx.company_id,
            product_id=product_id,
            type="customer_return_in",
            qty_delta=qty,
            unit_cost=unit_cost,
            ref_type=SALE_RETURN_ITEM_REF,
            ref_id=return_item_id,
            created_by=ctx.user_id,
        )
    )
    _flush(
        session,
        movement,
        details={
            "product_id": str(product_id),
            "ref_type": SALE_RETURN_ITEM_REF,
            "qty": str(qty),
            "unit_cost": str(unit_cost),
        },
    )
    # Pas d'audit critique : c'est le retour qui est l'opération auditée, pas la
    # rentrée de stock qui en découle — même partage qu'à la confirmation de vente.
    _emit_stock_updated(session, ctx, movement)
    return movement


def sale_out_movements(
    session: Session, ctx: TenantContext, sale_item_ids: Sequence[UUID]
) -> list[InventoryMovement]:
    """Sorties de stock d'une vente, dans l'ordre où elles ont été écrites.

    Façade de lecture pour l'annulation : Sales connaît ses lignes, pas le journal.
    """
    repository = InventoryMovementRepository(session, ctx)
    return list(repository.for_references(SALE_ITEM_REF, sale_item_ids))


def reverse_sale_out(
    session: Session, ctx: TenantContext, movement: InventoryMovement
) -> InventoryMovement:
    """Rend au stock la marchandise d'une sortie de vente annulée (§ 5.2 étape 2).

    Le mouvement d'origine n'est ni modifié ni supprimé : l'inverse le désigne par
    `reversal_of_movement_id`, et `inv_reversal_uq` garantit qu'il n'y en aura
    qu'un (T15). Aucun audit ici non plus : c'est l'annulation de la vente qui est
    l'opération auditée, et elle porte le motif.
    """
    return _write_reversal(session, ctx, movement)


class WatchedProduct(NamedTuple):
    """Un article sous son seuil ou épuisé, pour la carte « À surveiller »."""

    product_id: UUID
    name: str
    unit: str
    qty_on_hand: Decimal
    status: str


def _under_threshold(session: Session, ctx: TenantContext) -> list[tuple[UUID, Decimal, Decimal]]:
    """(produit, quantité, seuil) de chaque produit retombé à son seuil ou en dessous.

    Deux requêtes, pas une jointure : `products` porte le seuil, `product_stock` porte
    la quantité, et les deux tables appartiennent à des modules différents. Inventory
    passe donc par la façade de Products (décision 01).
    """
    thresholds = products_service.reorder_points(session, ctx)
    if not thresholds:
        return []
    stocks = ProductStockRepository(session, ctx).many(list(thresholds))
    return [
        (product_id, stock.qty_on_hand, threshold)
        for product_id, threshold in thresholds.items()
        if (stock := stocks.get(product_id)) is not None and stock.qty_on_hand <= threshold
    ]


def stock_alert_count(session: Session, ctx: TenantContext) -> int:
    """Nombre de produits dont le stock est retombé à son seuil d'alerte ou en dessous."""
    return len(_under_threshold(session, ctx))


def stock_to_watch(session: Session, ctx: TenantContext, *, limit: int) -> list[WatchedProduct]:
    """Les articles les plus urgents : épuisés d'abord, puis les plus bas par rapport à
    leur seuil (ADR 0070). Comparer au seuil plutôt qu'à la quantité : 2 sacs de riz et
    2 savons ne pressent pas autant."""

    def urgency(row: tuple[UUID, Decimal, Decimal]) -> tuple[Decimal, Decimal]:
        _, qty, threshold = row
        return (qty / threshold if threshold > 0 else Decimal("0"), qty)

    under = sorted(_under_threshold(session, ctx), key=urgency)
    summaries = products_service.get_summaries(session, ctx, [row[0] for row in under])
    watched: list[WatchedProduct] = []
    for product_id, qty, threshold in under:
        summary = summaries.get(product_id)
        if summary is None:
            continue
        watched.append(
            WatchedProduct(product_id, summary.name, summary.unit, qty, _status(qty, threshold))
        )
        if len(watched) == limit:
            break
    return watched


def average_on_hand(
    session: Session,
    ctx: TenantContext,
    *,
    product_ids: Sequence[UUID],
    period_from: date,
    period_to: date,
    timezone: str,
) -> dict[UUID, Decimal]:
    """Stock moyen détenu par produit sur la période, reconstitué depuis le journal.

    Exposé pour la métrique « rotation du stock » de la bande E (ADR 0033). Le stock
    courant ne suffit pas : un article écoulé puis réapprovisionné afficherait une
    rotation absurde. La moyenne porte sur les quantités de **fin de journée**, jours
    creux compris.

    Aucun module ne lit `inventory_movements` directement : cette façade est le seul
    accès, comme l'exige la règle des dépendances.
    """
    return StockHistoryRepository(session, ctx).average_on_hand(
        product_ids=product_ids,
        period_from=period_from,
        period_to=period_to,
        timezone=timezone,
    )


def daily_on_hand(
    session: Session,
    ctx: TenantContext,
    *,
    product_ids: Sequence[UUID],
    period_from: date,
    period_to: date,
    timezone: str,
) -> list[tuple[UUID, date, Decimal, date | None]]:
    """Stock de fin de journée, jour par jour, reconstitué depuis le journal.

    Façade pour CoGes Intelligence : le signal de rupture est le stock **à la date**,
    pas celui d'aujourd'hui (§ 6.2). Sans lui, un article à succès en rupture
    ressemble à un article sans demande, et sa prévision s'effondre durablement.

    Chaque ligne porte aussi le premier jour où le journal connaît le produit, pour
    qu'un stock nul **avant** tout mouvement ne soit pas lu comme une rupture.
    """
    return StockHistoryRepository(session, ctx).daily_on_hand(
        product_ids=product_ids,
        period_from=period_from,
        period_to=period_to,
        timezone=timezone,
    )


def rebuild_stock(session: Session, ctx: TenantContext) -> list[StockRebuildLine]:
    """Rejoue le journal et réaligne la projection (§ 5.7).

    La quantité est une somme, mais le CMP dépend de l'ordre des mouvements :
    la fonction `rebuild_product_stock` rejoue `(occurred_at, id)` croissant avec la
    **même** formule que le trigger. Aucun calcul n'est refait ici.

    `_rebuilt` est une table temporaire `ON COMMIT DROP` : un seul appel par
    transaction, donc une transaction par entreprise.
    """
    rows = session.execute(_REBUILD_SQL, {"company_id": ctx.company_id}).all()
    gaps = [
        StockRebuildLine(
            product_id=row.product_id, qty_ecart=row.qty_ecart, avg_ecart=row.avg_ecart
        )
        for row in rows
    ]
    for gap in gaps:
        # Un écart signale un antidatage ou une intervention hors API : il doit
        # rester lisible après coup, donc audit critique et non simple log.
        audit_critical(
            session,
            ctx,
            action=AuditAction.REBUILD,
            entity_table="product_stock",
            entity_id=gap.product_id,
            after={"qty_ecart": str(gap.qty_ecart), "avg_ecart": str(gap.avg_ecart)},
        )
    return gaps


# -------------------------------------------------------------------- privés


def _flush(session: Session, movement: InventoryMovement, *, details: dict[str, Any]) -> None:
    """Pousse l'insertion, traduit le refus éventuel, puis relit le mouvement.

    La relecture n'est pas une précaution : les triggers `BEFORE INSERT` réécrivent
    la ligne. `t20_inv_apply` estampille `unit_cost` au CMP sur toute sortie, et
    `t10_inv_check_reversal` reprend `unit_cost`, `ref_type` et `ref_id` du
    mouvement d'origine. Sans `refresh`, l'API renverrait les valeurs envoyées, pas
    celles écrites — un coût de sortie à zéro, par exemple.
    """
    try:
        session.flush()
    except (IntegrityError, DBAPIError) as exc:
        business_error = _translate(exc, details=details)
        if business_error is None:
            raise
        raise business_error from exc
    session.refresh(movement)


def _write_reversal(
    session: Session, ctx: TenantContext, origin: InventoryMovement
) -> InventoryMovement:
    """Écrit l'inverse exact d'un mouvement, après avoir vérifié qu'il est annulable."""
    repository = InventoryMovementRepository(session, ctx)

    if origin.reversal_of_movement_id is not None:
        raise NotReversibleError(details={"movement_id": str(origin.id)})
    if repository.reversal_of(origin.id) is not None:
        # Contrôle applicatif indispensable, pas seulement confortable : les
        # triggers `BEFORE INSERT` s'exécutent **avant** la vérification d'unicité,
        # et une seconde annulation serait annoncée comme un manque de stock.
        raise AlreadyReversedError(details={"movement_id": str(origin.id)})

    reversal = repository.add(
        InventoryMovement(
            company_id=ctx.company_id,
            product_id=origin.product_id,
            # Le type de l'inverse reste sémantique (§ 4.8) : `customer_return_in`
            # pour une sortie de vente annulée, `adjustment` pour toute correction
            # d'inventaire — ce qui garde les rapports de mouvements lisibles.
            type="customer_return_in" if origin.type == "sale_out" else "adjustment",
            qty_delta=-origin.qty_delta,
            # Écrasés par `t10_inv_check_reversal`, qui reprend ceux de l'origine.
            unit_cost=origin.unit_cost,
            reversal_of_movement_id=origin.id,
            note=f"Annulation du mouvement {origin.id}",
            created_by=ctx.user_id,
        )
    )
    _flush(session, reversal, details={"movement_id": str(origin.id), "ref_type": origin.ref_type})
    _emit_stock_updated(session, ctx, reversal)
    return reversal


def _audited(movement: InventoryMovement) -> dict[str, Any]:
    """Vue d'un mouvement pour l'audit : ce qui engage, rien de plus."""
    return {
        "id": str(movement.id),
        "product_id": str(movement.product_id),
        "type": movement.type,
        "qty_delta": str(movement.qty_delta),
        "unit_cost": str(movement.unit_cost),
        "note": movement.note,
        "reason_code": movement.reason_code,
    }


def _emit_stock_updated(session: Session, ctx: TenantContext, movement: InventoryMovement) -> None:
    """Relit la projection et pose `stock.updated` dans la transaction."""
    stock = ProductStockRepository(session, ctx).get(movement.product_id)
    if stock is None:  # pragma: no cover - le trigger vient de la créer
        raise NotFoundError("Projection de stock introuvable après le mouvement.")
    session.refresh(stock)

    summaries = products_service.get_summaries(session, ctx, [movement.product_id])
    reorder_point = None
    summary = summaries.get(movement.product_id)
    if summary is not None:
        reorder_point = summary.reorder_point

    emit(
        session,
        ctx,
        event_type=EventType.STOCK_UPDATED,
        aggregate_type=AGGREGATE_TYPE,
        aggregate_id=movement.product_id,
        payload=stock_updated_payload(
            product_id=movement.product_id,
            qty_on_hand=stock.qty_on_hand,
            avg_cost=stock.avg_cost,
            movement_id=movement.id,
            below_reorder_point=(reorder_point is not None and stock.qty_on_hand <= reorder_point),
        ),
    )
