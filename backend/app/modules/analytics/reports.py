"""Les chiffres des exports PDF pour le comptable (prompt 35, bloc X, ADR 0114).

Chaque rapport est lu **par les façades** qui servent déjà l'écran correspondant, avec la
même règle : c'est ce qui garantit que le PDF dit exactement ce que l'écran dit pour la
même période (tests `test_accountant_pdf.py`). Aucune requête ici, aucun HTTP ; la mise en
page vit dans `documents.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core import clock
from app.core.display import PAYMENT_METHODS
from app.core.errors import ValidationFailedError
from app.core.tenancy import NIL_USER_ID, TenantContext
from app.modules.analytics.schemas import CashJournalLine, CashLineKind
from app.modules.analytics.service import (
    CashPeriodTooBusyError,
    _bounds,
    _check_period,
    _method_rank,
    journal_lines,
)
from app.modules.companies import service as companies_service
from app.modules.customers import service as customers_service
from app.modules.expenses import service as expenses_service
from app.modules.finance import service as finance_service
from app.modules.inventory import service as inventory_service
from app.modules.sales import service as sales_service
from app.modules.suppliers import service as suppliers_service
from app.modules.users import service as users_service

ZERO = Decimal("0")
#: Ventes ou lignes de caisse lues par page, et au plus en tout : au-delà, la période est
#: trop chargée pour un document lisible (« réduisez la période »).
_PAGE = 100
MAX_CASH_LINES = 20_000
#: Bornes de l'ancienneté d'une dette, en jours (0-30, 31-60, 61-90, plus de 90).
AGING_BUCKETS: tuple[tuple[str, int | None], ...] = (
    ("0 à 30 jours", 30),
    ("31 à 60 jours", 60),
    ("61 à 90 jours", 90),
    ("Plus de 90 jours", None),
)

ReportKind = Literal["sales", "cash", "stock", "expenses", "debts"]


@dataclass(frozen=True, slots=True)
class Masthead:
    """L'en-tête commun : qui édite, pour qui, quand, sur quelle période."""

    company_name: str
    address: str | None
    phone: str | None
    ninea: str | None
    rc: str | None
    currency: str
    timezone: str
    logo_png: bytes | None
    edited_at: datetime
    edited_by: str
    period_from: date | None
    period_to: date | None


def masthead(
    session: Session,
    ctx: TenantContext,
    *,
    period_from: date | None = None,
    period_to: date | None = None,
) -> Masthead:
    company = companies_service.get_current_company(session, ctx)
    if ctx.user_id == NIL_USER_ID:
        author = "Accès support CoGes"
    else:
        author = users_service.names_by_id(session, ctx, [ctx.user_id]).get(ctx.user_id) or ""
    return Masthead(
        company_name=company.name,
        address=company.address,
        phone=company.phone,
        ninea=company.ninea,
        rc=company.rc,
        currency=company.currency,
        timezone=company.timezone,
        logo_png=companies_service.logo_png(session, ctx),
        edited_at=clock.now().astimezone(ZoneInfo(company.timezone)),
        edited_by=author,
        period_from=period_from,
        period_to=period_to,
    )


def check_period(period_from: date, period_to: date) -> None:
    """366 jours au plus, et la fin après le début (règle de l'écran Argent)."""
    _check_period(period_from, period_to)


def _method(method: str) -> str:
    return PAYMENT_METHODS.get(method, method)


# --------------------------------------------------------------------------- ventes


@dataclass(frozen=True, slots=True)
class SaleLine:
    sale_no: str
    sold_at: datetime
    customer: str
    total: Decimal
    paid: Decimal
    remaining: Decimal
    methods: str


@dataclass
class SalesReport:
    masthead: Masthead
    lines: list[SaleLine] = field(default_factory=list)
    #: (jour local, nombre de ventes, total), comme `GET /sales/day-totals`.
    by_day: list[tuple[date, int, Decimal]] = field(default_factory=list)
    #: Encaissé à la vente par moyen ; le reste du payé l'a été plus tard, sur la dette.
    by_method: list[tuple[str, Decimal]] = field(default_factory=list)
    settled_later: Decimal = ZERO
    subtotal: Decimal = ZERO
    discounts: Decimal = ZERO
    taxes: Decimal = ZERO
    total: Decimal = ZERO
    returned: Decimal = ZERO
    paid: Decimal = ZERO
    remaining: Decimal = ZERO
    cancelled_count: int = 0

    @property
    def net(self) -> Decimal:
        return self.total - self.returned


def sales_report(
    session: Session, ctx: TenantContext, *, period_from: date, period_to: date
) -> SalesReport:
    """Ventes confirmées de la période, par jour local (mêmes bornes que la liste)."""
    head = masthead(session, ctx, period_from=period_from, period_to=period_to)
    start, end = _bounds(period_from, period_to, head.timezone)
    zone = ZoneInfo(head.timezone)
    report = SalesReport(masthead=head)
    by_day: dict[date, list[Decimal]] = {}
    by_method: dict[str, Decimal] = {}
    page = 1
    while True:
        sales, total, returned = sales_service.list_sales(
            session,
            ctx,
            page=page,
            page_size=_PAGE,
            status="confirmed",
            date_from=start,
            date_to=end,
            include_drafts=False,
        )
        customers = customers_service.names_by_ids(
            session, ctx, [sale.customer_id for sale in sales if sale.customer_id]
        )
        paid_by_sale = finance_service.paid_by_sales(session, ctx, [sale.id for sale in sales])
        for sale in sales:
            direct = paid_by_sale.get(sale.id, {})
            ranked = sorted(direct.items(), key=lambda item: _method_rank(item[0]))
            for method, amount in ranked:
                by_method[method] = by_method.get(method, ZERO) + amount
            remaining = sale.total - sale.paid_total
            report.lines.append(
                SaleLine(
                    sale_no=sale.sale_no,
                    sold_at=sale.sold_at.astimezone(zone),
                    customer=customers.get(sale.customer_id, "") if sale.customer_id else "",
                    total=sale.total,
                    paid=sale.paid_total,
                    remaining=remaining,
                    methods=" + ".join(_method(m) for m, _ in ranked) or "À crédit",
                )
            )
            report.subtotal += sale.subtotal
            report.discounts += sale.discount_total
            report.taxes += sale.tax_total
            report.total += sale.total
            report.paid += sale.paid_total
            report.remaining += remaining
            report.returned += returned.get(sale.id, ZERO)
            day = by_day.setdefault(sale.sold_at.astimezone(zone).date(), [ZERO, ZERO])
            day[0] += 1
            day[1] += sale.total
        if page * _PAGE >= total:
            break
        page += 1
    report.lines.sort(key=lambda line: (line.sold_at, line.sale_no))
    report.by_day = [(day, int(count), amount) for day, (count, amount) in sorted(by_day.items())]
    report.by_method = [
        (_method(method), amount)
        for method, amount in sorted(by_method.items(), key=lambda item: _method_rank(item[0]))
    ]
    report.settled_later = report.paid - sum(by_method.values(), ZERO)
    _, cancelled_count, _ = sales_service.list_sales(
        session,
        ctx,
        page=1,
        page_size=1,
        status="cancelled",
        date_from=start,
        date_to=end,
        include_drafts=False,
    )
    report.cancelled_count = cancelled_count
    return report


# --------------------------------------------------------------------------- caisse


@dataclass
class CashReport:
    masthead: Masthead
    opening: Decimal
    cash_in: Decimal
    cash_out: Decimal
    #: (jour local, entré, sorti).
    by_day: list[tuple[date, Decimal, Decimal]]
    by_method: list[tuple[str, Decimal]]
    lines: list[CashJournalLine]

    @property
    def closing(self) -> Decimal:
        return self.opening + self.cash_in - self.cash_out


def cash_report(
    session: Session, ctx: TenantContext, *, period_from: date, period_to: date
) -> CashReport:
    """Entrées et sorties de la période, compensations exclues, soldes de début et de fin.

    Mêmes règles que l'écran 17 et l'écran 21 (`finance_service.cash_summary` : ni
    compensation, ni paiement annulé, ni annulation). Les lignes annulées sont listées
    sans être comptées, comme à l'écran.
    """
    head = masthead(session, ctx, period_from=period_from, period_to=period_to)
    start, end = _bounds(period_from, period_to, head.timezone)
    before = finance_service.cash_summary(
        session,
        ctx,
        period_from=datetime(1970, 1, 1, tzinfo=UTC),
        period_to=start - timedelta(microseconds=1),
    )
    cash = finance_service.cash_summary(session, ctx, period_from=start, period_to=end)
    days: dict[date, list[Decimal]] = {}
    for day, direction, total in finance_service.daily_cash(
        session, ctx, period_from=start, period_to=end, timezone=head.timezone
    ):
        pair = days.setdefault(day, [ZERO, ZERO])
        pair[0 if direction == "inflow" else 1] += total
    by_method = finance_service.cash_by_method(session, ctx, period_from=start, period_to=end)
    raw = finance_service.cash_journal(
        session, ctx, period_from=start, period_to=end, limit=MAX_CASH_LINES + 1
    )
    if len(raw) > MAX_CASH_LINES:
        raise CashPeriodTooBusyError
    lines = journal_lines(session, ctx, list(reversed(raw)))
    return CashReport(
        masthead=head,
        opening=before["inflow"] - before["outflow"],
        cash_in=cash["inflow"],
        cash_out=cash["outflow"],
        by_day=[(day, pair[0], pair[1]) for day, pair in sorted(days.items())],
        by_method=[
            (_method(method), net)
            for method, net in sorted(by_method.items(), key=lambda item: _method_rank(item[0]))
        ],
        lines=lines,
    )


def cash_line_label(line: CashJournalLine) -> str:
    """Ce qu'une ligne de caisse raconte, en mots (comme la liste de l'écran 21)."""
    number = (line.document_no or "").rsplit("-", 1)[-1].lstrip("0") or line.document_no or ""
    who = f" — {line.party_name}" if line.party_name else ""
    kind = line.kind
    if kind is CashLineKind.SALE:
        text = f"Vente n° {number}{who}"
    elif kind is CashLineKind.DEBT_IN:
        text = f"Dette réglée{who}"
    elif kind is CashLineKind.DEBT_OUT:
        text = f"Fournisseur payé{who}"
    elif kind is CashLineKind.EXPENSE:
        label = f" : {line.expense_label}" if line.expense_label else ""
        text = f"Dépense{who}{label}"
    elif kind is CashLineKind.REFUND:
        text = f"Remboursement, retour n° {number}{who}"
    else:
        text = "Autre entrée" if line.signed_amount >= 0 else "Autre sortie"
    if line.is_reversal:
        return f"Annulation : {text}"
    if line.cancelled:
        return f"{text} (annulé)"
    return text


# ---------------------------------------------------------------------------- stock


@dataclass(frozen=True, slots=True)
class StockReportLine:
    name: str
    category: str
    qty: Decimal
    unit: str
    avg_cost: Decimal
    value: Decimal
    tracked: bool


@dataclass
class StockReport:
    masthead: Masthead
    lines: list[StockReportLine]
    total_value: Decimal


def stock_report(session: Session, ctx: TenantContext) -> StockReport:
    """État du stock **à l'instant** : l'historique ne garde pas le CMP après chaque
    mouvement, une date passée demanderait de rejouer tout le journal (ADR 0114)."""
    head = masthead(session, ctx)
    lines: list[StockReportLine] = []
    page = 1
    while True:
        items, total = inventory_service.get_stock(session, ctx, page=page, page_size=_PAGE)
        lines += [
            StockReportLine(
                name=item.name,
                category=item.category_name or "Sans rayon",
                qty=item.qty_on_hand,
                unit=item.unit,
                avg_cost=item.avg_cost,
                value=item.stock_value,
                tracked=item.is_stock_tracked,
            )
            for item in items
        ]
        if page * _PAGE >= total:
            break
        page += 1
    lines.sort(key=lambda line: (line.category.casefold(), line.name.casefold()))
    summary = inventory_service.stock_summary(session, ctx)
    return StockReport(masthead=head, lines=lines, total_value=summary.stock_value)


# ------------------------------------------------------------------------- dépenses


@dataclass(frozen=True, slots=True)
class ExpenseLine:
    expense_no: str
    spent_at: date
    category: str
    label: str
    amount: Decimal


@dataclass
class ExpensesReport:
    masthead: Masthead
    by_category: list[tuple[str, Decimal]]
    lines: list[ExpenseLine]
    total: Decimal


def expenses_report(
    session: Session, ctx: TenantContext, *, period_from: date, period_to: date
) -> ExpensesReport:
    """Dépenses vivantes de la période, par type puis en détail (règle de l'écran 20)."""
    _check_period(period_from, period_to)
    head = masthead(session, ctx, period_from=period_from, period_to=period_to)
    by_category = expenses_service.totals_by_category(
        session, ctx, period_from=period_from, period_to=period_to
    )
    lines: list[ExpenseLine] = []
    page = 1
    while True:
        rows, total = expenses_service.list_expenses(
            session, ctx, page=page, page_size=_PAGE, period_from=period_from, period_to=period_to
        )
        lines += [
            ExpenseLine(
                expense_no=expense.expense_no,
                spent_at=expense.spent_at,
                category=category_name,
                label=expense.label,
                amount=expense.amount,
            )
            for expense, category_name, _ in rows
        ]
        if page * _PAGE >= total:
            break
        page += 1
    lines.sort(key=lambda line: (line.category.casefold(), line.spent_at, line.expense_no))
    return ExpensesReport(
        masthead=head,
        by_category=[(name, amount) for _, name, amount in by_category],
        lines=lines,
        total=sum((amount for _, _, amount in by_category), ZERO),
    )


# ---------------------------------------------------------------------------- dettes


def aging_bucket(opened_on: date, today: date) -> int:
    """Rang de la tranche d'ancienneté : 0 à 30 jours ⇒ 0, … plus de 90 jours ⇒ 3."""
    days = (today - opened_on).days
    for index, (_, limit) in enumerate(AGING_BUCKETS):
        if limit is None or days <= limit:
            return index
    return len(AGING_BUCKETS) - 1


@dataclass
class PartyDebt:
    name: str
    since: date
    due_date: date | None
    #: Reste dû par tranche d'ancienneté, dans l'ordre de `AGING_BUCKETS`.
    buckets: list[Decimal]

    @property
    def total(self) -> Decimal:
        return sum(self.buckets, ZERO)


@dataclass
class DebtSection:
    title: str
    parties: list[PartyDebt]

    @property
    def buckets(self) -> list[Decimal]:
        return [sum((p.buckets[i] for p in self.parties), ZERO) for i in range(len(AGING_BUCKETS))]

    @property
    def total(self) -> Decimal:
        return sum(self.buckets, ZERO)


@dataclass
class DebtsReport:
    masthead: Masthead
    today: date
    sections: list[DebtSection]


def debts_report(session: Session, ctx: TenantContext) -> DebtsReport:
    """Qui doit quoi, depuis quand : dettes ouvertes à ce jour, par ancienneté.

    L'ancienneté se compte depuis la naissance de chaque dette, dans le fuseau de
    l'entreprise. Les totaux sont ceux des cartes « On vous doit » et « Vous devez » de
    l'écran 17 (`debt_summaries`, mêmes statuts ouverts).
    """
    head = masthead(session, ctx)
    zone = ZoneInfo(head.timezone)
    today = clock.today_in(head.timezone)
    debts = finance_service.open_debts(session, ctx)
    sections: list[DebtSection] = []
    for party_type, title in (
        ("customer", "Clients qui vous doivent"),
        ("supplier", "Ce que vous devez aux fournisseurs"),
    ):
        mine = [debt for debt in debts if debt.party_type == party_type]
        ids = list({debt.party_id for debt in mine})
        names = (
            customers_service.names_by_ids(session, ctx, ids)
            if party_type == "customer"
            else suppliers_service.names_by_ids(session, ctx, ids)
        )
        parties: dict[UUID, PartyDebt] = {}
        for debt in mine:
            opened = debt.opened_at.astimezone(zone).date()
            party = parties.setdefault(
                debt.party_id,
                PartyDebt(
                    name=names.get(debt.party_id, ""),
                    since=opened,
                    due_date=debt.due_date,
                    buckets=[ZERO] * len(AGING_BUCKETS),
                ),
            )
            party.since = min(party.since, opened)
            if debt.due_date is not None:
                party.due_date = min(party.due_date or debt.due_date, debt.due_date)
            party.buckets[aging_bucket(opened, today)] += debt.balance
        ordered = sorted(parties.values(), key=lambda p: (-p.total, p.name.casefold()))
        sections.append(DebtSection(title=title, parties=ordered))
    return DebtsReport(masthead=head, today=today, sections=sections)


# ------------------------------------------------------------------- façade des PDF

#: Droit de lecture de l'écran, puis droit d'export existant (ADR 0114, réponses du
#: propriétaire le 2026-11-04).
PDF_RIGHTS: dict[ReportKind, tuple[str, str]] = {
    "sales": ("sales:read", "sales:export"),
    "cash": ("analytics:read", "analytics:export"),
    "stock": ("inventory:read", "analytics:export"),
    "expenses": ("expenses:read", "analytics:export"),
    "debts": ("debts:read", "analytics:export"),
}


def report_kind(value: str) -> ReportKind:
    """Le type d'un rapport, vérifié (une chaîne venue de la file d'exports)."""
    if value not in PDF_RIGHTS:
        raise ValueError(f"rapport inconnu : {value}")
    return value


def can_export(ctx: TenantContext, kind: ReportKind) -> bool:
    return all(ctx.has_permission(code) for code in PDF_RIGHTS[kind])


@dataclass(frozen=True, slots=True)
class PdfReport:
    filename: str
    content: bytes


class PeriodRequiredError(ValidationFailedError):
    code = "period_required"
    default_message = "Choisissez la période du document."


def _period_of(period_from: date | None, period_to: date | None) -> tuple[date, date]:
    if period_from is None or period_to is None:
        raise PeriodRequiredError()
    check_period(period_from, period_to)
    return period_from, period_to


def pdf_report(
    session: Session,
    ctx: TenantContext,
    kind: ReportKind,
    *,
    period_from: date | None = None,
    period_to: date | None = None,
) -> PdfReport:
    """Le PDF d'un rapport : les chiffres de l'écran, mis en page (`documents.py`)."""
    from app.modules.analytics import documents

    if kind == "stock":
        stock = stock_report(session, ctx)
        return PdfReport(documents.filename(kind, stock.masthead), documents.render_stock(stock))
    if kind == "debts":
        debts = debts_report(session, ctx)
        return PdfReport(documents.filename(kind, debts.masthead), documents.render_debts(debts))
    first, last = _period_of(period_from, period_to)
    if kind == "sales":
        sales = sales_report(session, ctx, period_from=first, period_to=last)
        return PdfReport(documents.filename(kind, sales.masthead), documents.render_sales(sales))
    if kind == "cash":
        cash = cash_report(session, ctx, period_from=first, period_to=last)
        return PdfReport(documents.filename(kind, cash.masthead), documents.render_cash(cash))
    spent = expenses_report(session, ctx, period_from=first, period_to=last)
    return PdfReport(documents.filename(kind, spent.masthead), documents.render_expenses(spent))
