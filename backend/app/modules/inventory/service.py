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
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import BusinessRuleError, NotFoundError, constraint_name, sqlstate
from app.core.events.outbox import emit
from app.core.events.types import EventType
from app.core.tenancy import TenantContext
from app.modules.categories import service as categories_service
from app.modules.inventory.events import AGGREGATE_TYPE, stock_updated_payload
from app.modules.inventory.models import InventoryMovement, ProductStock
from app.modules.inventory.repository import (
    InventoryMovementRepository,
    ProductStockRepository,
    StockHistoryRepository,
)
from app.modules.inventory.schemas import (
    TYPES_REQUIRING_NOTE,
    MovementCreate,
    StockLine,
    StockRebuildLine,
)
from app.modules.products import service as products_service

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


def get_stock(
    session: Session, ctx: TenantContext, *, page: int, page_size: int
) -> tuple[list[StockLine], int]:
    """Stock valorisé d'une page d'articles, joint aux fiches produit.

    Deux requêtes plutôt qu'une jointure : Inventory (bande C) lit Products
    (bande B) **par sa façade**, jamais par son modèle ni son repository (ADR 0012).
    Les articles en rupture remontent en premier — c'est ce que le gérant cherche.
    """
    stock_repository = ProductStockRepository(session, ctx)
    rows = stock_repository.page(page=page, page_size=page_size)
    total = stock_repository.count()

    summaries = products_service.get_summaries(session, ctx, [row.product_id for row in rows])
    category_ids = [
        summary.category_id for summary in summaries.values() if summary.category_id is not None
    ]
    category_names = categories_service.get_names(session, ctx, category_ids)

    lines: list[StockLine] = []
    for row in rows:
        summary = summaries.get(row.product_id)
        if summary is None:
            # Produit supprimé logiquement : sa projection survit (le journal aussi),
            # mais la fiche n'est plus lisible. On ne devine rien, on n'affiche rien.
            continue
        lines.append(
            StockLine(
                product_id=row.product_id,
                sku=summary.sku,
                name=summary.name,
                category_id=summary.category_id,
                category_name=(
                    None if summary.category_id is None else category_names.get(summary.category_id)
                ),
                qty_on_hand=row.qty_on_hand,
                avg_cost=row.avg_cost,
                stock_value=row.stock_value,
                reorder_point=summary.reorder_point,
                status=_status(row.qty_on_hand, summary.reorder_point),
                last_movement_at=row.last_movement_at,
            )
        )
    return lines, total


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
    ip_address: str | None = None,
) -> InventoryMovement:
    """Écrit un mouvement, et avec lui le stock, l'audit et l'événement.

    Point d'entrée unique du stock : tout passe par ici, y compris les sorties de
    vente à partir de la phase 05.
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
    ref_type, ref_id = _reference(payload, idempotency_key)

    entry = InventoryMovement(
        company_id=ctx.company_id,
        product_id=payload.product_id,
        type=payload.type,
        qty_delta=payload.qty_delta,
        unit_cost=_entry_unit_cost(payload, current),
        ref_type=ref_type,
        ref_id=ref_id,
        supplier_id=payload.supplier_id,
        note=payload.note,
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

    if payload.type in TYPES_REQUIRING_NOTE:
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


def stock_alert_count(session: Session, ctx: TenantContext) -> int:
    """Nombre de produits dont le stock est retombé à son seuil d'alerte ou en dessous.

    Deux requêtes, pas une jointure : `products` porte le seuil, `product_stock` porte
    la quantité, et les deux tables appartiennent à des modules différents. Inventory
    passe donc par la façade de Products (décision 01).
    """
    thresholds = products_service.reorder_points(session, ctx)
    if not thresholds:
        return 0
    stocks = ProductStockRepository(session, ctx).many(list(thresholds))
    return sum(
        1
        for product_id, threshold in thresholds.items()
        if (stock := stocks.get(product_id)) is not None and stock.qty_on_hand <= threshold
    )


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
