"""Façade de services du module Sales.

La confirmation est **la** transaction de référence de l'architecture (Diagramme 4,
§ 5.1) : onze étapes, une seule transaction PostgreSQL, rollback complet si l'une
échoue. Jamais de vente sans mouvement de stock, jamais d'écriture financière
orpheline, jamais d'événement publié pour une vente inexistante.

Ce que ce module n'écrit **jamais** en Python :

* `sales.subtotal`, `discount_total`, `tax_total` — recalculés par le trigger
  `sale_recompute_totals` à chaque écriture sur `sale_items` ;
* `sales.total`, `sale_items.net_amount`, `tax_amount`, `line_total` — colonnes
  générées. L'égalité comptable est **produite** par la base (T24) ;
* `sales.paid_total` — maintenu par `sale_paid_rollup` depuis `payments` ;
* le stock — il passe par la façade Inventory, qui seule compose un mouvement.

Sales est en haut des dépendances : il lit Products, Customers, Companies,
Inventory et Finance par leurs **façades**, et aucun d'eux ne le connaît.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.codes import next_document_number
from app.core.errors import BusinessRuleError, NotFoundError, constraint_name, sqlstate
from app.core.events.outbox import emit
from app.core.events.types import EventType
from app.core.tenancy import TenantContext
from app.modules.companies import service as companies_service
from app.modules.customers import service as customers_service
from app.modules.finance import service as finance_service
from app.modules.finance.schemas import DebtRead, PaymentRead
from app.modules.inventory import service as inventory_service
from app.modules.products import service as products_service
from app.modules.products.schemas import ProductSummary
from app.modules.sales.events import (
    AGGREGATE_TYPE,
    confirmed_line_payload,
    sale_cancelled_payload,
    sale_confirmed_payload,
)
from app.modules.sales.models import Sale, SaleItem
from app.modules.sales.repository import SaleItemRepository, SaleRepository
from app.modules.sales.schemas import (
    ReceiptCompany,
    ReceiptCustomer,
    ReceiptLine,
    ReceiptRead,
    SaleCancel,
    SaleConfirm,
    SaleCreate,
    SaleDetail,
    SaleItemCreate,
    SaleItemRead,
    SaleItemUpdate,
    SaleRead,
    SaleUpdate,
)

#: Type de document numéroté par `document_counters` (ADR 0021).
DOCUMENT_TYPE = "sale"

# --------------------------------------------------------------- erreurs métier
# Une classe par règle, avec son code stable en anglais et son message en français.


class SaleNotDraftError(BusinessRuleError):
    code = "sale_not_draft"
    default_message = "Cette vente n'est plus un brouillon : elle ne peut plus être modifiée."


class SaleEmptyError(BusinessRuleError):
    code = "sale_empty"
    default_message = "Vente vide : ajouter au moins une ligne avant de confirmer."


class SaleNotConfirmedError(BusinessRuleError):
    code = "sale_not_confirmed"
    default_message = "Cette vente n'est pas confirmée."


class SaleAlreadyCancelledError(BusinessRuleError):
    code = "sale_already_cancelled"
    default_message = "Cette vente a déjà été annulée."


class SaleHasPaymentError(BusinessRuleError):
    code = "sale_has_payment"
    default_message = (
        "Cette vente a été encaissée : elle ne s'annule pas, elle se corrige par un retour."
    )


class SaleHasReturnsError(BusinessRuleError):
    code = "sale_has_returns"
    default_message = "Cette vente porte un retour : l'annulation n'est pas un substitut au retour."


class OverpaymentError(BusinessRuleError):
    code = "overpayment"
    default_message = "Le règlement dépasse le total de la vente."


class DiscountExceedsLineError(BusinessRuleError):
    code = "discount_exceeds_line"
    default_message = "La remise dépasse le montant de la ligne."


#: `restrict_violation` : `sale_items_frozen` refuse d'écrire sur une vente confirmée.
_RESTRICT_VIOLATION = "23001"
_CHECK_VIOLATION = "23514"


def _translate(exc: DBAPIError, *, details: dict[str, Any]) -> BusinessRuleError | None:
    """Traduit un refus de PostgreSQL en erreur métier, ou rend None.

    Le SQLSTATE et le nom de contrainte sont stables ; le texte du message ne l'est
    pas (ADR 0014). Rien d'autre n'est inspecté.
    """
    state = sqlstate(exc)
    if state == _RESTRICT_VIOLATION:
        return SaleNotDraftError(details=details)
    if state == _CHECK_VIOLATION and constraint_name(exc) == "sale_items_discount_bounds":
        return DiscountExceedsLineError(details=details)
    return None


def _flush(session: Session, entity: Sale | SaleItem, *, details: dict[str, Any]) -> None:
    """Pousse l'écriture, traduit le refus éventuel, puis relit la ligne.

    La relecture n'est pas une précaution : `sale_recompute_totals` réécrit l'en-tête
    à chaque ligne, et `net_amount`, `tax_amount`, `line_total` et `total` sont des
    colonnes générées. Sans `refresh`, l'API renverrait ce qu'on a envoyé, pas ce que
    la base a écrit (ADR 0018).
    """
    try:
        session.flush()
    except (IntegrityError, DBAPIError) as exc:
        business_error = _translate(exc, details=details)
        if business_error is None:
            raise
        raise business_error from exc
    session.refresh(entity)


# ------------------------------------------------------------------- lectures


def get_sale(session: Session, ctx: TenantContext, sale_id: UUID) -> Sale:
    """Vente du tenant courant. Celle d'une autre entreprise donne 404."""
    sale = SaleRepository(session, ctx).get(sale_id)
    if sale is None:
        raise NotFoundError("Vente introuvable.")
    return sale


def list_sales(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    status: str | None = None,
    customer_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sale_no: str | None = None,
) -> tuple[Sequence[Sale], int, set[UUID]]:
    """Page de ventes, avec l'ensemble de celles qui portent un retour.

    Le troisième élément évite une requête par ligne pour un drapeau d'affichage.
    """
    repository = SaleRepository(session, ctx)
    filters: dict[str, Any] = {
        "status": status,
        "customer_id": customer_id,
        "date_from": date_from,
        "date_to": date_to,
        "sale_no": sale_no,
    }
    sales = repository.page_filtered(page=page, page_size=page_size, **filters)
    total = repository.count_filtered(**filters)
    return sales, total, repository.with_returns([sale.id for sale in sales])


def get_items(session: Session, ctx: TenantContext, sale_id: UUID) -> Sequence[SaleItem]:
    """Lignes d'une vente, dans l'ordre de saisie."""
    return SaleItemRepository(session, ctx).for_sale(sale_id)


def has_returns(session: Session, ctx: TenantContext, sale_id: UUID) -> bool:
    """La vente porte-t-elle au moins un retour ? Information dérivée, pas un statut."""
    return sale_id in SaleRepository(session, ctx).with_returns([sale_id])


# -------------------------------------------------------------------- brouillon


def _assert_draft(sale: Sale) -> None:
    """Un brouillon, et rien d'autre, se modifie. Le trigger reste l'autorité."""
    if sale.status != "draft":
        raise SaleNotDraftError(details={"sale_id": str(sale.id), "status": sale.status})


def create_sale(session: Session, ctx: TenantContext, payload: SaleCreate) -> Sale:
    """Ouvre un brouillon. **Aucun effet de bord** (§ 5.1, étape 0).

    Pas de mouvement de stock, pas d'écriture financière, pas d'audit critique, pas
    d'événement : tout cela se déclenche à la confirmation, jamais avant.

    Le numéro est attribué tout de suite (ADR 0021) : un brouillon sans numéro ne
    se retrouve ni dans une liste, ni au téléphone. Un brouillon abandonné consomme
    donc un numéro — c'est le prix d'un identifiant utilisable dès la saisie.
    """
    if payload.customer_id is not None:
        customers_service.assert_exists(session, ctx, payload.customer_id)

    sale = Sale(
        company_id=ctx.company_id,
        customer_id=payload.customer_id,
        sale_no=next_document_number(session, ctx, DOCUMENT_TYPE),
        status="draft",
        subtotal=Decimal("0"),
        discount_total=Decimal("0"),
        tax_total=Decimal("0"),
        paid_total=Decimal("0"),
        created_by=ctx.user_id,
    )
    if payload.sold_at is not None:
        # Sans date saisie, on laisse le `DEFAULT now()` de PostgreSQL : affecter
        # `None` enverrait un NULL sur une colonne qui n'en accepte pas.
        sale.sold_at = payload.sold_at
    sale = SaleRepository(session, ctx).add(sale)
    _flush(session, sale, details={})
    return sale


def update_sale(session: Session, ctx: TenantContext, sale_id: UUID, payload: SaleUpdate) -> Sale:
    """Change le client ou la date d'un brouillon."""
    sale = get_sale(session, ctx, sale_id)
    _assert_draft(sale)

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return sale
    if changes.get("customer_id") is not None:
        customers_service.assert_exists(session, ctx, changes["customer_id"])

    for field, value in changes.items():
        if field == "sold_at" and value is None:
            continue
        setattr(sale, field, value)
    _flush(session, sale, details={"sale_id": str(sale.id)})
    return sale


def add_item(
    session: Session, ctx: TenantContext, sale_id: UUID, payload: SaleItemCreate
) -> SaleItem:
    """Ajoute une ligne à un brouillon.

    Le prix et le taux inscrits ici sont **provisoires** : la confirmation les
    relira et les figera (§ 5.1 étape 3). Les écrire dès maintenant n'est pas une
    anticipation inutile — sans eux, le brouillon afficherait un total à zéro, et
    le caissier ne saurait pas ce qu'il doit encaisser.
    """
    sale = get_sale(session, ctx, sale_id)
    _assert_draft(sale)

    price = products_service.assert_sellable(session, ctx, payload.product_id)
    tax_rate = _line_tax_rate(session, ctx, payload.product_id)

    item = SaleItemRepository(session, ctx).add(
        SaleItem(
            company_id=ctx.company_id,
            sale_id=sale.id,
            product_id=payload.product_id,
            price_id=price.price_id,
            qty=payload.qty,
            unit_price=price.unit_price,
            unit_cost=Decimal("0"),
            discount=payload.discount,
            tax_rate=tax_rate,
        )
    )
    _flush(
        session,
        item,
        details={
            "product_id": str(payload.product_id),
            "unit_price": str(price.unit_price),
            "discount": str(payload.discount),
        },
    )
    return item


def update_item(
    session: Session,
    ctx: TenantContext,
    sale_id: UUID,
    item_id: UUID,
    payload: SaleItemUpdate,
) -> SaleItem:
    """Corrige la quantité ou la remise d'une ligne de brouillon."""
    sale = get_sale(session, ctx, sale_id)
    _assert_draft(sale)
    item = _get_item(session, ctx, sale, item_id)

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is not None:
            setattr(item, field, value)
    _flush(
        session,
        item,
        details={"sale_id": str(sale.id), "item_id": str(item_id)},
    )
    return item


def remove_item(session: Session, ctx: TenantContext, sale_id: UUID, item_id: UUID) -> None:
    """Retire une ligne d'un brouillon (ADR 0020)."""
    sale = get_sale(session, ctx, sale_id)
    _assert_draft(sale)
    item = _get_item(session, ctx, sale, item_id)

    repository = SaleItemRepository(session, ctx)
    repository.remove(item)
    try:
        session.flush()
    except (IntegrityError, DBAPIError) as exc:
        business_error = _translate(exc, details={"sale_id": str(sale_id)})
        if business_error is None:
            raise
        raise business_error from exc


# ----------------------------------------------------------------- confirmation


def confirm_sale(
    session: Session,
    ctx: TenantContext,
    sale_id: UUID,
    payload: SaleConfirm,
    *,
    ip_address: str | None = None,
) -> Sale:
    """Confirme une vente, dans l'ordre du § 5.1, en une seule transaction.

    Ce service n'ouvre ni ne valide aucune transaction : c'est la dépendance
    `get_tenant_session` qui l'a ouverte et qui la validera. Une exception levée
    ici — stock insuffisant, plafond de crédit, prix disparu — remonte jusqu'à
    elle et annule **tout** : la vente reste `draft`, aucun mouvement ne subsiste,
    aucun événement n'est écrit, le stock est intact (T39).
    """
    # 1. Vente verrouillée, brouillon, non vide.
    repository = SaleRepository(session, ctx)
    sale = repository.get_for_update(sale_id)
    if sale is None:
        raise NotFoundError("Vente introuvable.")
    if sale.status != "draft":
        raise SaleNotDraftError(details={"sale_id": str(sale.id), "status": sale.status})

    # 2. Lignes ordonnées par `product_id` croissant : c'est cet ordre, et lui
    #    seul, qui élimine l'interblocage entre deux caisses vendant les deux
    #    mêmes articles (§ 5). Le verrou de stock est posé par `t20_inv_apply`.
    item_repository = SaleItemRepository(session, ctx)
    items = item_repository.for_sale_ordered_by_product(sale.id)
    if not items:
        raise SaleEmptyError(details={"sale_id": str(sale.id)})

    summaries = products_service.get_summaries(session, ctx, [item.product_id for item in items])
    tax_enabled = companies_service.is_tax_enabled(session, ctx)

    lines: list[dict[str, str]] = []
    for item in items:
        # 3. Snapshots : prix et intervalle ouverts, taux figé.
        price = products_service.assert_sellable(session, ctx, item.product_id)
        item.price_id = price.price_id
        item.unit_price = price.unit_price
        item.tax_rate = _tax_rate_for(summaries.get(item.product_id), tax_enabled=tax_enabled)

        # 4-5. Sortie de stock au CMP, puis recopie du coût dans la ligne.
        item.unit_cost = _release_stock(session, ctx, item, summaries.get(item.product_id))
        _flush(
            session,
            item,
            details={
                "sale_id": str(sale.id),
                "product_id": str(item.product_id),
                "unit_price": str(price.unit_price),
            },
        )
        lines.append(
            confirmed_line_payload(
                sale_item_id=item.id,
                product_id=item.product_id,
                qty=item.qty,
                unit_price=item.unit_price,
                unit_cost=item.unit_cost,
                net_amount=item.net_amount,
                tax_amount=item.tax_amount,
            )
        )

    # 6. La vente passe confirmée. Les totaux, eux, sont déjà à jour : chaque
    #    écriture de ligne a déclenché `sale_recompute_totals`.
    session.refresh(sale)
    total = sale.total
    if payload.paid_amount > total:
        raise OverpaymentError(
            details={"paid_amount": str(payload.paid_amount), "total": str(total)}
        )

    sale.status = "confirmed"
    sale.confirmed_at = datetime.now(UTC)
    _flush(session, sale, details={"sale_id": str(sale.id)})

    # 7. Volet financier : ce qui est encaissé, puis ce qui reste dû.
    if payload.paid_amount > 0:
        finance_service.record_sale_payment(
            session,
            ctx,
            sale_id=sale.id,
            amount=payload.paid_amount,
            method=payload.method,
            ip_address=ip_address,
        )
    outstanding = total - payload.paid_amount
    if outstanding > 0:
        finance_service.open_customer_debt(
            session,
            ctx,
            sale_id=sale.id,
            customer_id=sale.customer_id,
            principal=outstanding,
            due_date=None if payload.due_date is None else payload.due_date.date(),
            ip_address=ip_address,
        )

    # 8. Audit critique, puis outbox. Les deux dans la transaction.
    session.refresh(sale)
    audit_critical(
        session,
        ctx,
        action=AuditAction.CONFIRM,
        entity_table="sales",
        entity_id=sale.id,
        after=_audited(sale),
        ip_address=ip_address,
    )
    emit(
        session,
        ctx,
        event_type=EventType.SALE_CONFIRMED,
        aggregate_type=AGGREGATE_TYPE,
        aggregate_id=sale.id,
        payload=sale_confirmed_payload(
            sale_id=sale.id,
            sale_no=sale.sale_no,
            customer_id=sale.customer_id,
            sold_at=sale.sold_at,
            subtotal=sale.subtotal,
            discount_total=sale.discount_total,
            tax_total=sale.tax_total,
            total=sale.total,
            paid_total=sale.paid_total,
            lines=lines,
        ),
    )
    return sale


# ------------------------------------------------------------------- annulation


def cancel_sale(
    session: Session,
    ctx: TenantContext,
    sale_id: UUID,
    payload: SaleCancel,
    *,
    ip_address: str | None = None,
) -> Sale:
    """Annule une vente confirmée, dans l'ordre du § 5.2.

    L'annulation n'est **pas** un substitut au retour : une vente encaissée ou
    déjà retournée se corrige par un retour, pas en effaçant la trace. La règle
    est celle du § 5.2, telle quelle (ADR 0023).
    """
    repository = SaleRepository(session, ctx)
    sale = repository.get_for_update(sale_id)
    if sale is None:
        raise NotFoundError("Vente introuvable.")

    # 1. Refus : pas un brouillon, pas déjà annulée, pas de retour, pas d'encaissement.
    if sale.status == "cancelled":
        raise SaleAlreadyCancelledError(details={"sale_id": str(sale.id)})
    if sale.status != "confirmed":
        raise SaleNotConfirmedError(details={"sale_id": str(sale.id), "status": sale.status})
    if has_returns(session, ctx, sale.id):
        raise SaleHasReturnsError(details={"sale_id": str(sale.id)})
    if finance_service.has_settled_payment(session, ctx, sale.id):
        raise SaleHasPaymentError(
            details={"sale_id": str(sale.id), "paid_total": str(sale.paid_total)}
        )

    before = _audited(sale)

    # 2-3. Un mouvement inverse par sortie. `inv_reversal_uq` garantit l'unicité :
    #      une seconde annulation ne peut pas doubler le stock (T15).
    item_ids = [item.id for item in SaleItemRepository(session, ctx).for_sale(sale.id)]
    movements = inventory_service.sale_out_movements(session, ctx, item_ids)
    reversed_ids = [
        inventory_service.reverse_sale_out(session, ctx, movement).id for movement in movements
    ]

    # 4. Dette liée : abandonnée si rien n'a été réglé, refus sinon.
    finance_service.write_off_sale_debt(
        session, ctx, sale_id=sale.id, reason=payload.reason, ip_address=ip_address
    )

    # 5. Statut, date et motif. `sales_cancel_coherent` exige les trois ensemble.
    sale.status = "cancelled"
    sale.cancelled_at = datetime.now(UTC)
    sale.cancel_reason = payload.reason
    _flush(session, sale, details={"sale_id": str(sale.id)})

    audit_critical(
        session,
        ctx,
        action=AuditAction.CANCEL,
        entity_table="sales",
        entity_id=sale.id,
        before=before,
        after=_audited(sale),
        ip_address=ip_address,
    )
    emit(
        session,
        ctx,
        event_type=EventType.SALE_CANCELLED,
        aggregate_type=AGGREGATE_TYPE,
        aggregate_id=sale.id,
        payload=sale_cancelled_payload(
            sale_id=sale.id,
            sale_no=sale.sale_no,
            sold_at=sale.sold_at,
            total=sale.total,
            reason=payload.reason,
            reversed_movement_ids=reversed_ids,
        ),
    )
    return sale


# -------------------------------------------------------------------- privés


def _get_item(session: Session, ctx: TenantContext, sale: Sale, item_id: UUID) -> SaleItem:
    """Ligne appartenant à cette vente. Celle d'une autre vente donne 404."""
    item = SaleItemRepository(session, ctx).get_in_sale(sale.id, item_id)
    if item is None:
        raise NotFoundError("Ligne de vente introuvable.")
    return item


def _tax_rate_for(summary: ProductSummary | None, *, tax_enabled: bool) -> Decimal:
    """Taux à figer sur une ligne.

    Le paramètre d'entreprise l'emporte sur le taux du produit (ADR 0022) : une
    entreprise non assujettie ne facture aucune taxe, même sur un produit qui en
    porte une au référentiel. Le taux du produit y reste, pour le jour où elle le
    deviendra — mais aucune vente passée ne sera recalculée.
    """
    if not tax_enabled or summary is None:
        return Decimal("0")
    return summary.default_tax_rate


def _line_tax_rate(session: Session, ctx: TenantContext, product_id: UUID) -> Decimal:
    """Taux provisoire d'une ligne de brouillon."""
    if not companies_service.is_tax_enabled(session, ctx):
        return Decimal("0")
    return products_service.get_tax_rate(session, ctx, product_id)


def _release_stock(
    session: Session, ctx: TenantContext, item: SaleItem, summary: ProductSummary | None
) -> Decimal:
    """Sort la marchandise et rend le coût à figer sur la ligne (§ 5.1 étapes 4-5).

    Un article non suivi en stock ne produit aucun mouvement, et son COGS vaut 0 :
    il n'a pas de coût moyen, puisqu'il n'a pas d'entrées.
    """
    if summary is None or not summary.is_stock_tracked:
        return Decimal("0")
    movement = inventory_service.record_sale_out(
        session, ctx, product_id=item.product_id, qty=item.qty, sale_item_id=item.id
    )
    return movement.unit_cost


def _audited(sale: Sale) -> dict[str, Any]:
    """Vue d'une vente pour l'audit : ce qui engage, rien de plus."""
    return {
        "id": str(sale.id),
        "sale_no": sale.sale_no,
        "status": sale.status,
        "customer_id": None if sale.customer_id is None else str(sale.customer_id),
        "total": str(sale.total),
        "paid_total": str(sale.paid_total),
        "cancel_reason": sale.cancel_reason,
    }


# ------------------------------------------------------------------ assemblages
# Les vues de lecture appartiennent au service : elles orchestrent plusieurs
# façades. Le router, lui, ne fait que les appeler (ADR 0010).


def build_read(sale: Sale, *, has_returns: bool) -> SaleRead:
    """En-tête d'une vente, tel que la liste l'affiche.

    `balance` et `has_returns` sont dérivés, jamais stockés : le solde est une
    soustraction, et « retournée » n'est pas un statut de `sale_status`.
    """
    return SaleRead(
        id=sale.id,
        sale_no=sale.sale_no,
        customer_id=sale.customer_id,
        status=sale.status,
        sold_at=sale.sold_at,
        subtotal=sale.subtotal,
        discount_total=sale.discount_total,
        tax_total=sale.tax_total,
        total=sale.total,
        paid_total=sale.paid_total,
        balance=sale.total - sale.paid_total,
        has_returns=has_returns,
        cancel_reason=sale.cancel_reason,
        confirmed_at=sale.confirmed_at,
        cancelled_at=sale.cancelled_at,
    )


def build_detail(session: Session, ctx: TenantContext, sale: Sale) -> SaleDetail:
    """Vente complète : en-tête, lignes, règlements et dette éventuelle."""
    header = build_read(sale, has_returns=has_returns(session, ctx, sale.id))
    debt = finance_service.debt_for_sale(session, ctx, sale.id)
    return SaleDetail(
        **header.model_dump(),
        items=[SaleItemRead.model_validate(item) for item in get_items(session, ctx, sale.id)],
        payments=[
            PaymentRead.model_validate(payment)
            for payment in finance_service.payments_for_sale(session, ctx, sale.id)
        ],
        debt=None if debt is None else DebtRead.model_validate(debt),
    )


def build_receipt(session: Session, ctx: TenantContext, sale_id: UUID) -> ReceiptRead:
    """Reçu d'une vente, en JSON (ADR 0022).

    Refusé sur un brouillon : un reçu atteste d'une transaction qui a eu lieu.
    Une vente annulée en garde un, au contraire — c'est la pièce qui explique
    pourquoi le client est reparti sans rien.

    Tout y est figé. Le prix, le taux et la remise viennent de la ligne, pas du
    référentiel : le reçu d'une vente de l'an dernier reste exact même si les
    tarifs ont changé depuis. Seuls le nom du produit et son SKU sont relus —
    c'est un libellé, pas un montant.
    """
    sale = get_sale(session, ctx, sale_id)
    if sale.status == "draft":
        raise SaleNotConfirmedError(details={"sale_id": str(sale.id), "status": sale.status})

    items = get_items(session, ctx, sale.id)
    summaries = products_service.get_summaries(session, ctx, [item.product_id for item in items])
    company = companies_service.get_current_company(session, ctx)

    customer = None
    if sale.customer_id is not None:
        record = customers_service.get_customer(session, ctx, sale.customer_id)
        customer = ReceiptCustomer(id=record.id, code=record.code, name=record.name)

    lines: list[ReceiptLine] = []
    for item in items:
        summary = summaries.get(item.product_id)
        lines.append(
            ReceiptLine(
                product_id=item.product_id,
                sku="" if summary is None else summary.sku,
                name="Produit supprimé" if summary is None else summary.name,
                qty=item.qty,
                unit_price=item.unit_price,
                discount=item.discount,
                tax_rate=item.tax_rate,
                tax_amount=item.tax_amount,
                line_total=item.line_total,
            )
        )

    return ReceiptRead(
        sale_id=sale.id,
        sale_no=sale.sale_no,
        status=sale.status,
        sold_at=sale.sold_at,
        confirmed_at=sale.confirmed_at,
        company=ReceiptCompany(name=company.name, currency=company.currency),
        customer=customer,
        lines=lines,
        subtotal=sale.subtotal,
        discount_total=sale.discount_total,
        tax_total=sale.tax_total,
        total=sale.total,
        paid_total=sale.paid_total,
        balance=sale.total - sale.paid_total,
        payments=[
            PaymentRead.model_validate(payment)
            for payment in finance_service.payments_for_sale(session, ctx, sale.id)
        ],
    )
