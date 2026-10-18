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
* `sales.paid_total` — maintenu par `sale_paid_rollup` et `pa_sale_rollup` (ADR 0062) ;
* le stock — il passe par la façade Inventory, qui seule compose un mouvement.

Sales est en haut des dépendances : il lit Products, Customers, Companies,
Inventory et Finance par leurs **façades**, et aucun d'eux ne le connaît.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core import money
from app.core.audit import AuditAction, audit_critical
from app.core.codes import DOCUMENT_PREFIXES, DOCUMENT_WIDTH, next_document_number
from app.core.errors import BusinessRuleError, NotFoundError, constraint_name, sqlstate
from app.core.events.outbox import emit
from app.core.events.types import EventType
from app.core.tenancy import TenantContext
from app.modules.companies import service as companies_service
from app.modules.customers import service as customers_service
from app.modules.finance import service as finance_service
from app.modules.finance.schemas import (
    OFFSET_METHOD,
    DebtRead,
    DebtStatus,
    RefundLinkRead,
)
from app.modules.inventory import service as inventory_service
from app.modules.products import service as products_service
from app.modules.products.schemas import ProductSummary
from app.modules.sales.events import (
    AGGREGATE_TYPE,
    RETURN_AGGREGATE_TYPE,
    confirmed_line_payload,
    returned_line_payload,
    sale_cancelled_payload,
    sale_confirmed_payload,
    sale_return_refunded_payload,
    sale_returned_payload,
)
from app.modules.sales.models import Sale, SaleItem, SaleReturn, SaleReturnItem
from app.modules.sales.repository import (
    SaleHistoryRepository,
    SaleItemRepository,
    SaleRepository,
    SaleReturnItemRepository,
    SaleReturnRepository,
    SaleRevenueRepository,
)
from app.modules.sales.schemas import (
    CustomerChoice,
    CustomerChoicePage,
    ReceiptCompany,
    ReceiptCustomer,
    ReceiptLine,
    ReceiptRead,
    RefundCreate,
    SaleCancel,
    SaleConfirm,
    SaleCreate,
    SaleDayTotal,
    SaleDayTotals,
    SaleDetail,
    SaleItemCreate,
    SaleItemRead,
    SaleItemUpdate,
    SaleRead,
    SaleReturnCreate,
    SaleReturnDetail,
    SaleReturnItemRead,
    SaleReturnList,
    SaleReturnRead,
    SaleUpdate,
)
from app.modules.users import service as users_service

#: Types de documents numérotés par `document_counters` (ADR 0021).
DOCUMENT_TYPE = "sale"
RETURN_DOCUMENT_TYPE = "sale_return"

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


class ReturnBeforeSaleError(BusinessRuleError):
    code = "return_before_sale"
    default_message = "Date invalide : un retour ne peut pas précéder la vente."


class ReturnInFutureError(BusinessRuleError):
    code = "return_in_future"
    default_message = "Date invalide : un retour ne peut pas être daté dans le futur."


class ReturnLineNotInSaleError(BusinessRuleError):
    code = "return_line_not_in_sale"
    default_message = "Ligne rendue inconnue : elle n'appartient pas à cette vente."


class ReturnQtyExceedsSoldError(BusinessRuleError):
    code = "return_qty_exceeds_sold"
    default_message = "Quantité rendue supérieure à ce qui reste retournable sur cette ligne."


class NoDebtToOffsetError(BusinessRuleError):
    code = "no_debt_to_offset"
    default_message = "Aucune dette ouverte sur cette vente : ce retour ne peut rien compenser."


class OffsetExceedsDebtError(BusinessRuleError):
    code = "offset_exceeds_debt"
    default_message = "Compensation supérieure au solde de la dette."


#: `restrict_violation` : `sale_items_frozen` refuse d'écrire sur une vente confirmée.
_RESTRICT_VIOLATION = "23001"
_CHECK_VIOLATION = "23514"

#: SQLSTATE applicatif levé par `return_item_check()` (migration 0008, ADR 0026).
_RETURN_QTY_CAP = "CG040"


def _translate(exc: DBAPIError, *, details: dict[str, Any]) -> BusinessRuleError | None:
    """Traduit un refus de PostgreSQL en erreur métier, ou rend None.

    Le SQLSTATE et le nom de contrainte sont stables ; le texte du message ne l'est
    pas (ADR 0014). Rien d'autre n'est inspecté.
    """
    state = sqlstate(exc)
    if state == _RETURN_QTY_CAP:
        return ReturnQtyExceedsSoldError(details=details)
    if state == _RESTRICT_VIOLATION:
        return SaleNotDraftError(details=details)
    if state == _CHECK_VIOLATION and constraint_name(exc) == "sale_items_discount_bounds":
        return DiscountExceedsLineError(details=details)
    return None


def _flush(
    session: Session,
    entity: Sale | SaleItem | SaleReturn | SaleReturnItem,
    *,
    details: dict[str, Any],
) -> None:
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


#: Clients récents en tête de la liste de vente (ADR 0063).
RECENT_CUSTOMERS = 5


def customer_choices(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
) -> CustomerChoicePage:
    """Liste des clients de « Nouvelle vente » (ADR 0063).

    Sans recherche : la page 1 commence par les clients des dernières ventes, puis tous
    les autres par ordre alphabétique, sans doublon. Avec une recherche : l'ordre de
    pertinence de l'ADR 0050. Chaque ligne dit ce que le client doit encore.
    """
    term = search.strip() if search else None
    recent: list[Any] = []
    if not term:
        recent = customers_service.get_many(
            session,
            ctx,
            SaleRepository(session, ctx).recent_customer_ids(limit=RECENT_CUSTOMERS),
        )
    others, others_total = customers_service.list_customers(
        session,
        ctx,
        page=page,
        page_size=page_size,
        search=term or None,
        exclude_ids=[customer.id for customer in recent],
    )
    shown = [*(recent if page == 1 else []), *others]
    debts = finance_service.open_balances_by_customer(
        session, ctx, [customer.id for customer in shown]
    )
    recent_ids = {customer.id for customer in recent}
    return CustomerChoicePage(
        items=[
            CustomerChoice(
                id=customer.id,
                name=customer.name,
                phone=customer.phone,
                open_debt=debts.get(customer.id, Decimal("0")),
                recent=customer.id in recent_ids,
            )
            for customer in shown
        ],
        page=page,
        page_size=page_size,
        total=others_total + len(recent),
    )


#: Un numéro de vente tapé dans la recherche : « V-001044 », « v1044 » ou « 1044 ».
_SALE_NUMBER = re.compile(r"(?:v\s*-?\s*)?0*(\d{1,9})", re.IGNORECASE)


def sale_number_of(term: str) -> str | None:
    """Numéro de vente complet que désigne un terme tapé, ou `None` s'il n'en est pas un.

    Le commerçant lit « Vente n° 1044 » : il doit retrouver V-001044 en tapant 1044. Le
    numéro reste comparé **exactement**, jamais par `LIKE` (ADR 0013).
    """
    match = _SALE_NUMBER.fullmatch(term.strip())
    if match is None:
        return None
    return f"{DOCUMENT_PREFIXES[DOCUMENT_TYPE]}-{int(match.group(1)):0{DOCUMENT_WIDTH}d}"


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
    search: str | None = None,
    state: str | None = None,
    include_drafts: bool = True,
    mine: bool = False,
) -> tuple[Sequence[Sale], int, dict[UUID, Decimal]]:
    """Page de ventes, avec le total retourné de celles qui portent un retour.

    Le troisième élément évite une requête par ligne : une vente absente de ce
    dictionnaire n'a aucun retour, une vente présente en a au moins un — fût-il
    intégralement remisé, donc d'un remboursable nul.

    `search` trouve un numéro exact ou les ventes des clients dont le nom répond
    (ADR 0070) ; `state` filtre par état de paiement, dérivé. `include_drafts=False` : la
    liste de la maquette, sans brouillon ; `mine` : les ventes saisies par l'utilisateur
    courant (« Nouvelle vente » reprend son brouillon du jour).
    """
    repository = SaleRepository(session, ctx)
    filters: dict[str, Any] = {
        "status": status,
        "customer_id": customer_id,
        "date_from": date_from,
        "date_to": date_to,
        "state": state,
        "include_drafts": include_drafts,
        "created_by": ctx.user_id if mine else None,
    }
    term = search.strip() if search else ""
    if term:
        filters["sale_no"] = sale_number_of(term)
        filters["search_customer_ids"] = customers_service.ids_matching(session, ctx, term)
    sales = repository.page_filtered(page=page, page_size=page_size, **filters)
    total = repository.count_filtered(**filters)
    return sales, total, repository.returned_totals([sale.id for sale in sales])


def day_totals(
    session: Session,
    ctx: TenantContext,
    *,
    date_from: datetime,
    date_to: datetime,
    state: str | None = None,
    search: str | None = None,
) -> SaleDayTotals:
    """Ventes par jour, dans le fuseau de l'entreprise, avec les filtres de la liste
    (ADR 0070) : en tête de chaque groupe, et dans le résumé du jour."""
    filters: dict[str, Any] = {"state": state}
    term = search.strip() if search else ""
    if term:
        filters["sale_no"] = sale_number_of(term)
        filters["search_customer_ids"] = customers_service.ids_matching(session, ctx, term)
    rows = SaleRepository(session, ctx).day_totals(
        date_from=date_from,
        date_to=date_to,
        timezone=companies_service.get_timezone(session, ctx),
        **filters,
    )
    return SaleDayTotals(
        items=[
            SaleDayTotal(
                day=day, sale_count=count, confirmed_count=confirmed, total=money.amount(total)
            )
            for day, count, confirmed, total in rows
        ]
    )


def customer_names_of_lines(
    session: Session,
    ctx: TenantContext,
    *,
    sale_item_ids: Sequence[UUID],
    return_item_ids: Sequence[UUID],
) -> dict[UUID, str | None]:
    """Nom du client derrière chaque ligne de vente ou de retour (« Vendu à Awa Diop »,
    ADR 0071) ; `None` pour un client de passage."""
    repository = SaleItemRepository(session, ctx)
    customers = {
        **repository.customer_ids_by_item(sale_item_ids),
        **repository.customer_ids_by_return_item(return_item_ids),
    }
    names = customers_service.names_by_ids(
        session, ctx, [value for value in customers.values() if value is not None]
    )
    return {
        line_id: None if customer_id is None else names.get(customer_id)
        for line_id, customer_id in customers.items()
    }


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


def _locked_draft(session: Session, ctx: TenantContext, sale_id: UUID) -> Sale:
    """Le brouillon, verrouillé comme le fait `confirm_sale` (ADR 0087).

    Sans ce verrou, une ligne écrite pendant la confirmation passait
    `sale_items_no_change` (la vente était encore `draft` pour elle), puis son recalcul
    des totaux attendait le COMMIT de la confirmation et changeait le total après le
    calcul de la dette, sans sortie de stock. Verrouillée d'abord, l'écriture attend la
    confirmation et relit `confirmed` : refus propre. Même premier verrou que
    `confirm_sale`, donc aucun interblocage entre les deux.
    """
    sale = SaleRepository(session, ctx).get_for_update(sale_id)
    if sale is None:
        raise NotFoundError("Vente introuvable.")
    _assert_draft(sale)
    return sale


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
    sale = _locked_draft(session, ctx, sale_id)

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
    sale = _locked_draft(session, ctx, sale_id)

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
    sale = _locked_draft(session, ctx, sale_id)
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
    sale = _locked_draft(session, ctx, sale_id)
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
    # La dette avant la vente : c'est l'ordre d'un règlement, que le trigger
    # `pa_sale_rollup` prolonge jusqu'à la vente (ADR 0062). L'ordre inverse
    # s'interbloquerait avec un règlement simultané.
    finance_service.lock_sale_debt(session, ctx, sale_id)
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


def build_read(
    sale: Sale,
    *,
    returned_total: Decimal | None,
    customer_name: str | None,
    debt_status: DebtStatus | None,
    item_count: int,
) -> SaleRead:
    """En-tête d'une vente, tel que la liste l'affiche.

    Tout ce qui touche aux retours est dérivé, jamais stocké : le solde est une
    soustraction, et « retournée » n'est pas un statut de `sale_status`. `None`
    signifie « aucun retour » — et se distingue d'un retour intégralement remisé,
    dont le remboursable est nul mais qui a bien eu lieu.
    """
    return SaleRead(
        id=sale.id,
        sale_no=sale.sale_no,
        customer_id=sale.customer_id,
        customer_name=customer_name,
        status=sale.status,
        sold_at=sale.sold_at,
        subtotal=sale.subtotal,
        discount_total=sale.discount_total,
        tax_total=sale.tax_total,
        total=sale.total,
        paid_total=sale.paid_total,
        balance=sale.total - sale.paid_total,
        debt_status=debt_status,
        has_returns=returned_total is not None,
        returned_total=Decimal("0") if returned_total is None else returned_total,
        cancel_reason=sale.cancel_reason,
        confirmed_at=sale.confirmed_at,
        cancelled_at=sale.cancelled_at,
        item_count=item_count,
    )


def build_page(
    session: Session,
    ctx: TenantContext,
    sales: Sequence[Sale],
    returned_totals: dict[UUID, Decimal],
) -> list[SaleRead]:
    """En-têtes d'une page de ventes : noms des clients et statuts des dettes, un appel chacun."""
    names = customers_service.names_by_ids(
        session, ctx, [sale.customer_id for sale in sales if sale.customer_id is not None]
    )
    debt_statuses = finance_service.debt_statuses_for_sales(
        session, ctx, [sale.id for sale in sales]
    )
    item_counts = SaleItemRepository(session, ctx).counts_by_sale([sale.id for sale in sales])
    return [
        build_read(
            sale,
            returned_total=returned_totals.get(sale.id),
            customer_name=None if sale.customer_id is None else names.get(sale.customer_id),
            debt_status=debt_statuses.get(sale.id),
            item_count=item_counts.get(sale.id, 0),
        )
        for sale in sales
    ]


def build_item_reads(
    session: Session, ctx: TenantContext, items: Sequence[SaleItem]
) -> list[SaleItemRead]:
    """Lignes de vente, avec les libellés du produit et la quantité déjà retournée.

    Les libellés sont relus au référentiel comme sur le reçu : ce sont des noms, pas
    des montants (ADR 0050). Deux requêtes par lot, jamais une par ligne.
    """
    summaries = products_service.get_summaries(session, ctx, [item.product_id for item in items])
    returned = SaleReturnItemRepository(session, ctx).returned_qty_by_item(
        [item.id for item in items]
    )
    reads: list[SaleItemRead] = []
    for item in items:
        summary = summaries.get(item.product_id)
        reads.append(
            SaleItemRead(
                id=item.id,
                product_id=item.product_id,
                product_name=None if summary is None else summary.name,
                sku=None if summary is None else summary.sku,
                price_id=item.price_id,
                qty=item.qty,
                unit_price=item.unit_price,
                unit_cost=item.unit_cost,
                discount=item.discount,
                tax_rate=item.tax_rate,
                net_amount=item.net_amount,
                tax_amount=item.tax_amount,
                line_total=item.line_total,
                returned_qty=returned.get(item.id, Decimal("0")),
            )
        )
    return reads


def build_detail(session: Session, ctx: TenantContext, sale: Sale) -> SaleDetail:
    """Vente complète : en-tête, lignes, règlements et dette éventuelle."""
    header = build_page(
        session, ctx, [sale], SaleRepository(session, ctx).returned_totals([sale.id])
    )[0]
    debt = finance_service.debt_for_sale(session, ctx, sale.id)
    return SaleDetail(
        **header.model_dump(),
        seller_name=seller_name(session, ctx, sale),
        items=build_item_reads(session, ctx, get_items(session, ctx, sale.id)),
        payments=finance_service.payment_reads_for_sale(session, ctx, sale.id),
        debt=None if debt is None else DebtRead.model_validate(debt),
    )


def seller_name(session: Session, ctx: TenantContext, sale: Sale) -> str | None:
    """Nom de l'utilisateur qui a saisi la vente ; `None` s'il n'existe plus."""
    return users_service.names_by_id(session, ctx, [sale.created_by]).get(sale.created_by)


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
        customer = ReceiptCustomer(
            id=record.id, code=record.code, name=record.name, phone=record.phone
        )

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
        company=ReceiptCompany(
            name=company.name,
            currency=company.currency,
            address=company.address,
            phone=company.phone,
            wave_number=company.wave_number,
            ninea=company.ninea,
            rc=company.rc,
            receipt_footer=company.receipt_footer,
        ),
        customer=customer,
        seller_name=seller_name(session, ctx, sale),
        lines=lines,
        subtotal=sale.subtotal,
        discount_total=sale.discount_total,
        tax_total=sale.tax_total,
        total=sale.total,
        paid_total=sale.paid_total,
        balance=sale.total - sale.paid_total,
        payments=finance_service.payment_reads_for_sale(session, ctx, sale.id),
    )


# ------------------------------------------------------------------- retours
# Un retour n'annule pas une vente : il enregistre que de la marchandise est
# revenue. La vente reste vraie, ses totaux ne bougent pas, et son statut ne
# change pas — « retournée » est une information dérivée (§ 4.6).


def get_return(session: Session, ctx: TenantContext, return_id: UUID) -> SaleReturn:
    """Retour du tenant courant. Celui d'une autre entreprise donne 404."""
    sale_return = SaleReturnRepository(session, ctx).get(return_id)
    if sale_return is None:
        raise NotFoundError("Retour introuvable.")
    return sale_return


def list_returns_for_sale(
    session: Session, ctx: TenantContext, sale_id: UUID
) -> Sequence[SaleReturn]:
    """Retours d'une vente, du plus récent au plus ancien."""
    get_sale(session, ctx, sale_id)
    return SaleReturnRepository(session, ctx).for_sale(sale_id)


def _refund_amounts(item: SaleItem, qty: Decimal) -> tuple[Decimal, Decimal]:
    """Remboursable TTC et part de taxe d'une quantité rendue (§ 4.7).

    Le § 4.7 donne `qty × (unit_price − discount/qty) × (1 + tax_rate)`. La remise de
    la ligne est donc **proratisée** : rendre 3 articles sur 10 rend trois dixièmes de
    la remise, pas la remise entière ni rien.

    L'arrondi, lui, reproduit exactement les colonnes générées de `sale_items` : on
    arrondit le net et la taxe **séparément**, puis on les additionne. Un seul arrondi
    sur le TTC ferait mieux au centime près sur un retour partiel, mais rendrait
    parfois un centime de moins que `line_total` sur un retour **total** — et un
    client qui rend tout ce qu'il a acheté doit récupérer ce qu'il a payé, à l'unité
    de centime. Contrepartie assumée : la somme de plusieurs retours partiels peut
    s'écarter d'un centime du total de la ligne.
    """
    gross = qty * item.unit_price
    prorated_discount = item.discount * qty / item.qty
    net_before_tax = gross - prorated_discount
    tax_refund = money.amount(net_before_tax * item.tax_rate)
    return money.amount(net_before_tax) + tax_refund, tax_refund


def create_return(
    session: Session,
    ctx: TenantContext,
    sale_id: UUID,
    payload: SaleReturnCreate,
    *,
    ip_address: str | None = None,
) -> SaleReturn:
    """Enregistre un retour sur une vente confirmée, dans l'ordre du § 5.3.

    Comme la confirmation, ce service n'ouvre ni ne valide aucune transaction. Si la
    troisième ligne dépasse la quantité vendue, rien ne subsiste : ni l'en-tête, ni
    les deux premières lignes, ni leurs rentrées de stock, ni le numéro de retour.
    """
    # 1. Vente verrouillée et confirmée. Un brouillon n'a rien vendu ; une vente
    #    annulée a déjà tout repris — dans les deux cas il n'y a rien à rendre.
    sale = SaleRepository(session, ctx).get_for_update(sale_id)
    if sale is None:
        raise NotFoundError("Vente introuvable.")
    if sale.status != "confirmed":
        raise SaleNotConfirmedError(details={"sale_id": str(sale.id), "status": sale.status})

    # 2. Date métier bornée des deux côtés. Aucun délai maximal de retour en V1 : rien
    #    dans le modèle n'en impose un, et l'inventer ferait refuser des retours
    #    légitimes (ADR 0025).
    now = datetime.now(UTC)
    returned_at = now if payload.returned_at is None else payload.returned_at
    if returned_at < sale.sold_at:
        raise ReturnBeforeSaleError(
            details={"returned_at": returned_at.isoformat(), "sold_at": sale.sold_at.isoformat()}
        )
    if returned_at > now:
        raise ReturnInFutureError(details={"returned_at": returned_at.isoformat()})

    # 3. Lignes demandées, rapportées aux lignes de la vente. L'ordre de parcours est
    #    celui des `product_id` croissants, comme à la confirmation : c'est lui qui
    #    élimine l'interblocage entre deux caisses touchant les deux mêmes articles.
    #    `sri_check` verrouille en plus la ligne de vente, `t20_inv_apply` le stock.
    requested = {line.sale_item_id: line.qty for line in payload.lines}
    items = {
        item.id: item
        for item in SaleItemRepository(session, ctx).for_sale_ordered_by_product(sale.id)
    }
    unknown = set(requested) - set(items)
    if unknown:
        raise ReturnLineNotInSaleError(
            details={"sale_item_ids": sorted(str(item_id) for item_id in unknown)}
        )
    returned_items = [items[item_id] for item_id in items if item_id in requested]
    summaries = products_service.get_summaries(
        session, ctx, [item.product_id for item in returned_items]
    )

    # 4. En-tête. `total_refund`, `refunded_total` et `refund_status` ne sont pas
    #    fournis : les triggers `sri_totals` et `sr_status` les écrivent, et le
    #    numéro vient du compteur de l'entreprise (ADR 0021).
    sale_return = SaleReturnRepository(session, ctx).add(
        SaleReturn(
            company_id=ctx.company_id,
            sale_id=sale.id,
            return_no=next_document_number(session, ctx, RETURN_DOCUMENT_TYPE),
            reason=payload.reason,
            returned_at=returned_at,
            created_by=ctx.user_id,
        )
    )
    _flush(session, sale_return, details={"sale_id": str(sale.id)})

    lines: list[dict[str, str]] = []
    for item in returned_items:
        qty = requested[item.id]
        refund_amount, tax_refund = _refund_amounts(item, qty)

        # 5. Montants figés aux prix et taux historiques, coût recopié de la ligne.
        return_item = SaleReturnItemRepository(session, ctx).add(
            SaleReturnItem(
                company_id=ctx.company_id,
                return_id=sale_return.id,
                sale_item_id=item.id,
                qty=qty,
                refund_amount=refund_amount,
                tax_refund=tax_refund,
                unit_cost=item.unit_cost,
            )
        )
        # Détails capturés avant le flush risqué : après un rejet, la transaction est
        # morte et relire un attribut expiré échouerait à son tour (ADR 0010).
        _flush(
            session,
            return_item,
            details={
                "sale_item_id": str(item.id),
                "requested": str(qty),
                "sold": str(item.qty),
            },
        )

        # 6. Rentrée en stock, au coût de sortie. Un article non suivi n'en produit
        #    aucune, exactement comme il n'avait produit aucune sortie.
        summary = summaries.get(item.product_id)
        if summary is not None and summary.is_stock_tracked:
            inventory_service.record_customer_return_in(
                session,
                ctx,
                product_id=item.product_id,
                qty=qty,
                unit_cost=item.unit_cost,
                return_item_id=return_item.id,
            )

        lines.append(
            returned_line_payload(
                return_item_id=return_item.id,
                sale_item_id=item.id,
                product_id=item.product_id,
                qty=qty,
                refund_amount=refund_amount,
                tax_refund=tax_refund,
                unit_cost=item.unit_cost,
            )
        )

    # 7. Audit critique, puis outbox — les deux dans la transaction.
    session.refresh(sale_return)
    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT,
        entity_table="sale_returns",
        entity_id=sale_return.id,
        after=_audited_return(sale_return),
        ip_address=ip_address,
    )
    emit(
        session,
        ctx,
        event_type=EventType.SALE_RETURNED,
        aggregate_type=AGGREGATE_TYPE,
        aggregate_id=sale.id,
        payload=sale_returned_payload(
            return_id=sale_return.id,
            return_no=sale_return.return_no,
            sale_id=sale.id,
            sale_no=sale.sale_no,
            sold_at=sale.sold_at,
            returned_at=sale_return.returned_at,
            total_refund=sale_return.total_refund,
            lines=lines,
        ),
    )
    return sale_return


def refund_return(
    session: Session,
    ctx: TenantContext,
    return_id: UUID,
    payload: RefundCreate,
    *,
    ip_address: str | None = None,
) -> SaleReturn:
    """Règle tout ou partie d'un retour, dans l'ordre du § 5.4.

    Deux règlements sont possibles, et le gérant choisit : la trésorerie, ou la
    compensation d'une dette du client par ce qui lui est dû (`offset`, ADR 0024).
    Le troisième cas du § 5.3 — ne rien régler — ne s'appelle pas : c'est l'état dans
    lequel le retour est né.

    Rembourser en plusieurs fois est prévu : le reste dû se recalcule à chaque appel,
    et `refund_status` passe par `partial` avant `settled` (T20).
    """
    # 1. Retour verrouillé, reste dû calculé sous ce verrou. Sans lui, deux
    #    remboursements concurrents liraient le même `refunded_total` et
    #    concluraient tous deux qu'il reste de quoi payer.
    repository = SaleReturnRepository(session, ctx)
    sale_return = repository.get_for_update(return_id)
    if sale_return is None:
        raise NotFoundError("Retour introuvable.")

    before = _audited_return(sale_return)
    due = sale_return.total_refund - sale_return.refunded_total
    details: dict[str, Any] = {
        "return_id": str(sale_return.id),
        "amount": str(payload.amount),
        "refund_due": str(due),
    }
    # Contrôle doublé, dans l'esprit de l'ADR 0014 : `refund_check` (`CG041`) reste
    # l'autorité, celui-ci ne sert qu'à nommer le reste dû dans le cas courant.
    if payload.amount > due:
        raise finance_service.RefundExceedsDueError(details=details)

    if payload.method == OFFSET_METHOD:
        # 2a. Compensation : l'argent ne sort pas, il éteint ce que le client doit.
        debt = finance_service.open_debt_for_sale(session, ctx, sale_return.sale_id)
        if debt is None:
            raise NoDebtToOffsetError(details=details)
        if payload.amount > debt.balance:
            raise OffsetExceedsDebtError(
                details={**details, "debt_id": str(debt.id), "balance": str(debt.balance)}
            )
        payment, _inflow = finance_service.record_return_offset(
            session,
            ctx,
            sale_return_id=sale_return.id,
            debt_id=debt.id,
            amount=payload.amount,
            ip_address=ip_address,
        )
    else:
        # 2b. Trésorerie : un `outflow` rattaché au retour, puis son lettrage.
        payment, _refund = finance_service.record_return_refund(
            session,
            ctx,
            sale_return_id=sale_return.id,
            amount=payload.amount,
            method=payload.method,
            reference=payload.reference,
            ip_address=ip_address,
        )

    # 3. `refunded_total` et `refund_status` viennent des triggers, jamais d'ici.
    session.refresh(sale_return)
    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="sale_returns",
        entity_id=sale_return.id,
        before=before,
        after=_audited_return(sale_return),
        ip_address=ip_address,
    )
    emit(
        session,
        ctx,
        event_type=EventType.SALE_RETURN_REFUNDED,
        aggregate_type=RETURN_AGGREGATE_TYPE,
        aggregate_id=sale_return.id,
        payload=sale_return_refunded_payload(
            return_id=sale_return.id,
            return_no=sale_return.return_no,
            sale_id=sale_return.sale_id,
            payment_id=payment.id,
            amount=payload.amount,
            method=payment.method,
            refunded_total=sale_return.refunded_total,
            total_refund=sale_return.total_refund,
            refund_status=sale_return.refund_status,
        ),
    )
    return sale_return


def _audited_return(sale_return: SaleReturn) -> dict[str, Any]:
    """Vue d'un retour pour l'audit : ce qui engage, rien de plus."""
    return {
        "id": str(sale_return.id),
        "return_no": sale_return.return_no,
        "sale_id": str(sale_return.sale_id),
        "total_refund": str(sale_return.total_refund),
        "refunded_total": str(sale_return.refunded_total),
        "refund_status": sale_return.refund_status,
        "reason": sale_return.reason,
    }


def build_return_read(sale_return: SaleReturn) -> SaleReturnRead:
    """En-tête d'un retour. `refund_due` est dérivé, jamais stocké."""
    return SaleReturnRead(
        id=sale_return.id,
        sale_id=sale_return.sale_id,
        return_no=sale_return.return_no,
        reason=sale_return.reason,
        returned_at=sale_return.returned_at,
        total_refund=sale_return.total_refund,
        refunded_total=sale_return.refunded_total,
        refund_status=sale_return.refund_status,
        refund_due=sale_return.total_refund - sale_return.refunded_total,
        created_at=sale_return.created_at,
    )


def build_return_detail(
    session: Session, ctx: TenantContext, sale_return: SaleReturn
) -> SaleReturnDetail:
    """Retour complet : lignes rendues, lettrages et décaissements.

    Les deux questions du § 5.4 se lisent ici dans le même sens : `refunds` donne les
    lettrages, `payments` les sorties correspondantes. L'autre sens — d'un paiement
    vers ses retours — est rendu par Finance, qui possède les paiements.
    """
    header = build_return_read(sale_return)
    return SaleReturnDetail(
        **header.model_dump(),
        items=[
            SaleReturnItemRead.model_validate(item)
            for item in SaleReturnItemRepository(session, ctx).for_return(sale_return.id)
        ],
        refunds=[
            RefundLinkRead.model_validate(refund)
            for refund in finance_service.refunds_for_return(session, ctx, sale_return.id)
        ],
        payments=finance_service.payment_reads_for_return(session, ctx, sale_return.id),
    )


def build_return_list(session: Session, ctx: TenantContext, sale_id: UUID) -> SaleReturnList:
    """Retours d'une vente. Une vente en porte une poignée : pas de pagination."""
    returns = list_returns_for_sale(session, ctx, sale_id)
    return SaleReturnList(
        items=[build_return_read(sale_return) for sale_return in returns], total=len(returns)
    )


# ------------------------------------- façade de restitution (bande E)


def revenue_totals(
    session: Session,
    ctx: TenantContext,
    *,
    period_from: datetime,
    period_to: datetime,
) -> dict[str, Decimal]:
    """Mesures de revenu et de coût de la période, telles que le § 4.10 les définit.

    Façade **lecture seule** pour la bande E : Analytics compose, Sales calcule sur
    ses propres tables. Aucun module ne lit `sale_items` à sa place.

        net_revenue = gross_revenue − discount_total − refund_net_amount
        cogs_net    = cogs_gross − cogs_returned

    Les retours sont rattachés au jour de la **vente d'origine**, et les ventes
    annulées comme les brouillons sont exclus. `tax_total` reste isolé : une taxe
    n'est pas un revenu (§ 4.10).
    """
    repository = SaleRevenueRepository(session, ctx)
    totals = repository.gross_totals(period_from=period_from, period_to=period_to)
    totals |= repository.return_totals(period_from=period_from, period_to=period_to)
    totals["net_revenue"] = (
        totals["gross_revenue"] - totals["discount_total"] - totals["refund_net_amount"]
    )
    totals["cogs_net"] = totals["cogs_gross"] - totals["cogs_returned"]
    totals["sale_count"] = Decimal(
        repository.confirmed_sale_count(period_from=period_from, period_to=period_to)
    )
    return totals


def confirmed_sale_count(
    session: Session,
    ctx: TenantContext,
    *,
    period_from: datetime,
    period_to: datetime,
) -> int:
    """Nombre de ventes confirmées sur la période — des tickets, pas des lignes.

    Exposé à part pour la bande E : ce compte ne peut **pas** se lire sur
    `daily_sales_facts`, dont le grain est jour × produit. Sommer `sale_count` sur les
    produits compterait deux fois une vente à deux articles (ADR 0034).
    """
    return SaleRevenueRepository(session, ctx).confirmed_sale_count(
        period_from=period_from, period_to=period_to
    )


# ------------------------------------------------------- historique au point D


class DailyProductSales(NamedTuple):
    """Une journée de vente d'un produit, telle qu'elle était connue au soir de D."""

    day: date
    product_id: UUID
    qty: Decimal
    revenue: Decimal
    cogs: Decimal
    sale_count: int


def daily_product_sales_as_of(
    session: Session,
    ctx: TenantContext,
    *,
    day_from: date,
    as_of: date,
    timezone: str,
) -> list[DailyProductSales]:
    """Ventes nettes jour × produit **connues au soir de `as_of`** (§ 6.2).

    Façade lecture seule pour CoGes Intelligence. Point-in-time strict (ADR 0035) :
    une vente annulée après D compte à D, un retour enregistré après D n'est pas
    encore déduit. Les horodatages sont ceux du métier (`sold_at`, `cancelled_at`,
    `returned_at`). Seuls les jours où le produit s'est vendu figurent : la série
    dense est l'affaire de l'appelant.
    """
    rows = SaleHistoryRepository(session, ctx).daily_product_sales(
        day_from=day_from, as_of=as_of, timezone=timezone
    )
    return [DailyProductSales(*row) for row in rows]


def first_sale_days_as_of(
    session: Session, ctx: TenantContext, *, as_of: date, timezone: str
) -> dict[UUID, date]:
    """Premier jour de vente connu à `as_of`, par produit."""
    return SaleHistoryRepository(session, ctx).first_sale_days(as_of=as_of, timezone=timezone)


# ------------------------------------------------- clients (écrans 13 et 14, ADR 0072)


def last_sale_at_by_customer(session: Session, ctx: TenantContext) -> dict[UUID, datetime]:
    """Dernière visite de chaque client : sa dernière vente confirmée."""
    return SaleRepository(session, ctx).last_sale_at_by_customer()


def customer_totals_since(
    session: Session, ctx: TenantContext, customer_id: UUID, since: datetime
) -> tuple[Decimal, int, datetime | None]:
    """Acheté par un client depuis `since` (montant, nombre de visites) ; sa dernière visite."""
    return SaleRepository(session, ctx).customer_totals_since(customer_id, since)


def sale_ids_of_customer(session: Session, ctx: TenantContext, customer_id: UUID) -> list[UUID]:
    """Ventes d'un client, pour retrouver ce qu'il a payé dessus."""
    return SaleRepository(session, ctx).ids_of_customer(customer_id)


def product_ids_by_sale(
    session: Session, ctx: TenantContext, sale_ids: Sequence[UUID]
) -> dict[UUID, list[UUID]]:
    """Articles de chaque vente, dans l'ordre de saisie."""
    return SaleItemRepository(session, ctx).product_ids_by_sale(sale_ids)


def sale_numbers(session: Session, ctx: TenantContext, sale_ids: Sequence[UUID]) -> dict[UUID, str]:
    """Numéro de chaque vente du lot (« V-001044 »)."""
    if not sale_ids:
        return {}
    return {sale.id: sale.sale_no for sale in SaleRepository(session, ctx).by_ids(sale_ids)}


class SaleHead(NamedTuple):
    """Ce qu'une ligne de caisse dit d'une vente : son numéro et son client."""

    sale_no: str
    customer_id: UUID | None


def sale_heads(
    session: Session, ctx: TenantContext, sale_ids: Sequence[UUID]
) -> dict[UUID, SaleHead]:
    """Numéro et client de chaque vente du lot (écran 21)."""
    if not sale_ids:
        return {}
    return {
        sale.id: SaleHead(sale.sale_no, sale.customer_id)
        for sale in SaleRepository(session, ctx).by_ids(list(set(sale_ids)))
    }


def return_heads(
    session: Session, ctx: TenantContext, return_ids: Sequence[UUID]
) -> dict[UUID, tuple[str, UUID]]:
    """Numéro et vente d'origine de chaque retour du lot (écran 21)."""
    if not return_ids:
        return {}
    return {
        sale_return.id: (sale_return.return_no, sale_return.sale_id)
        for sale_return in SaleReturnRepository(session, ctx).by_ids(list(set(return_ids)))
    }


def last_sale_at_by_product(session: Session, ctx: TenantContext) -> dict[UUID, datetime]:
    """Dernière vente confirmée de chaque article, pour « Vente rare » (ADR 0074)."""
    return SaleItemRepository(session, ctx).last_sale_at_by_product()
