"""Façade de services du module Analytics.

Compose, et possède **une** projection. Les charges viennent d'Expenses, la trésorerie
et les encours de Finance, le fuseau de Companies, le nombre de tickets et le calcul
de référence de Sales, le stock historique d'Inventory. Le revenu et le coût des
ventes, eux, se lisent sur `daily_sales_facts` : c'est la table de ce module, et la
promesse tenue de l'ADR 0030 — même réponse, autre source.

Une seule écriture, et elle ne vient jamais d'une requête HTTP : `rebuild_days`, que
le worker analytique appelle après COMMIT (ADR 0032). Aucun audit, aucun événement.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ValidationFailedError
from app.core.money import amount as to_amount
from app.core.money import quantity as to_quantity
from app.core.money import serialize
from app.core.tenancy import TenantContext
from app.modules.analytics.repository import DailySalesFactRepository
from app.modules.analytics.schemas import (
    DAILY_SERIES_DAYS,
    MAX_PERIOD_DAYS,
    MAX_RANKING_LIMIT,
    METRIC_LABELS,
    NAMED_ITEMS,
    PEOPLE_PAGE_SIZE,
    SERIES_LABELS,
    SUPPLIER_NAMED_PRODUCTS,
    CustomerSalePage,
    CustomerSaleRow,
    CustomerSheet,
    DailyCashPoint,
    DeliveryLineRow,
    FinanceOverview,
    PeoplePage,
    PersonPaymentPage,
    PersonPaymentRow,
    PersonRow,
    ProductHistory,
    ProductHistoryItem,
    ProductMetric,
    ProductRanking,
    ProductRankRow,
    SupplierDeliveryPage,
    SupplierDeliveryRow,
    SupplierSheet,
    Timeseries,
    TimeseriesMeasure,
    TimeseriesPoint,
)
from app.modules.companies import service as companies_service
from app.modules.customers import service as customers_service
from app.modules.expenses import service as expenses_service
from app.modules.finance import service as finance_service
from app.modules.intelligence import serving as intelligence_serving
from app.modules.inventory import service as inventory_service
from app.modules.products import service as products_service
from app.modules.sales import service as sales_service
from app.modules.suppliers import service as suppliers_service


class PeriodInvertedError(ValidationFailedError):
    code = "period_inverted"
    default_message = "La date de début doit précéder la date de fin."


class PeriodTooLongError(ValidationFailedError):
    code = "period_too_long"
    default_message = f"La période ne peut pas dépasser {MAX_PERIOD_DAYS} jours."


def _check_period(period_from: date, period_to: date) -> None:
    """Refuse une plage inversée ou plus longue que la borne du module."""
    if period_from > period_to:
        raise PeriodInvertedError(
            details={"from": period_from.isoformat(), "to": period_to.isoformat()}
        )
    if (period_to - period_from).days + 1 > MAX_PERIOD_DAYS:
        raise PeriodTooLongError(details={"max_days": MAX_PERIOD_DAYS})


def _bounds(period_from: date, period_to: date, timezone: str) -> tuple[datetime, datetime]:
    """Bornes instantanées d'une plage de jours, inclusives des deux côtés.

    Dans le fuseau de **l'entreprise**, pas en UTC. `daily_sales_facts.day` est le jour
    local de la vente (§ 4.10) : des bornes UTC décriraient une autre période dès
    qu'une entreprise n'est pas à l'heure de Greenwich, et T32 comparerait alors deux
    plages différentes. Un gérant qui demande « du 1er au 30 » désigne ses journées,
    pas celles de Londres.

    Le dernier jour va jusqu'à sa dernière microseconde, sans quoi les encaissements
    de l'après-midi disparaîtraient du total.
    """
    _check_period(period_from, period_to)
    zone = ZoneInfo(timezone)
    start = datetime.combine(period_from, time.min, tzinfo=zone)
    end = datetime.combine(period_to, time.max, tzinfo=zone)
    return start, end


def _daily_series(
    session: Session,
    ctx: TenantContext,
    *,
    period_from: date,
    period_to: date,
    timezone: str,
) -> list[DailyCashPoint]:
    """Trente derniers jours de la période, jours sans mouvement compris.

    Les jours vides sont rendus à zéro plutôt qu'omis : une courbe trouée se lit
    comme une absence de données, pas comme une caisse immobile.
    """
    first_day = max(period_from, period_to - timedelta(days=DAILY_SERIES_DAYS - 1))
    start, end = _bounds(first_day, period_to, timezone)

    totals: dict[date, dict[str, Decimal]] = {}
    for day, direction, total in finance_service.daily_cash(
        session, ctx, period_from=start, period_to=end, timezone=timezone
    ):
        totals.setdefault(day, {})[direction] = total

    series: list[DailyCashPoint] = []
    day = first_day
    while day <= period_to:
        cash_in = totals.get(day, {}).get("inflow", Decimal("0"))
        cash_out = totals.get(day, {}).get("outflow", Decimal("0"))
        series.append(
            DailyCashPoint(
                day=day,
                cash_in=to_amount(cash_in),
                cash_out=to_amount(cash_out),
                net_cash=to_amount(cash_in - cash_out),
            )
        )
        day += timedelta(days=1)
    return series


def finance_overview(
    session: Session,
    ctx: TenantContext,
    *,
    period_from: date,
    period_to: date,
) -> FinanceOverview:
    """Trésorerie, résultat estimé et encours d'une période.

    Marge brute = CA net HT − coût des ventes net, aux définitions exactes du
    § 4.10 ; résultat estimé = marge brute − charges de la période. Ce n'est pas un
    résultat comptable : ni amortissement, ni provision, ni charge à payer. C'est
    la question du gérant, pas celle de son expert-comptable (décision 09).
    """
    timezone = companies_service.get_timezone(session, ctx)
    start, end = _bounds(period_from, period_to, timezone)

    cash = finance_service.cash_summary(session, ctx, period_from=start, period_to=end)
    # Le revenu et le coût des ventes viennent des agrégats déjà calculés : aucune
    # requête HTTP ne balaye `sale_items` (décision 14). Seul le nombre de tickets
    # reste compté sur `sales` — le grain des faits ne permet pas de le déduire.
    revenue = DailySalesFactRepository(session, ctx).period_totals(
        period_from=period_from, period_to=period_to
    )
    sale_count = sales_service.confirmed_sale_count(session, ctx, period_from=start, period_to=end)
    expenses = expenses_service.totals_by_kind(
        session, ctx, period_from=period_from, period_to=period_to
    )
    debts = finance_service.open_debt_totals(session, ctx)

    expenses_total = expenses["fixed"] + expenses["variable"]
    gross_margin = revenue["net_revenue"] - revenue["cogs_net"]

    return FinanceOverview(
        period_from=period_from,
        period_to=period_to,
        cash_in=to_amount(cash["inflow"]),
        cash_out=to_amount(cash["outflow"]),
        net_cash=to_amount(cash["inflow"] - cash["outflow"]),
        net_revenue=to_amount(revenue["net_revenue"]),
        cogs_net=to_amount(revenue["cogs_net"]),
        gross_margin=to_amount(gross_margin),
        expenses_total=to_amount(expenses_total),
        fixed_expenses=to_amount(expenses["fixed"]),
        variable_expenses=to_amount(expenses["variable"]),
        estimated_result=to_amount(gross_margin - expenses_total),
        gross_revenue=to_amount(revenue["gross_revenue"]),
        discount_total=to_amount(revenue["discount_total"]),
        refund_net_amount=to_amount(revenue["refund_net_amount"]),
        tax_total=to_amount(revenue["tax_total"]),
        cogs_gross=to_amount(revenue["cogs_gross"]),
        cogs_returned=to_amount(revenue["cogs_returned"]),
        sale_count=sale_count,
        receivables_open=to_amount(debts["customer"]),
        payables_open=to_amount(debts["supplier"]),
        daily=_daily_series(
            session, ctx, period_from=period_from, period_to=period_to, timezone=timezone
        ),
    )


# --------------------------------------------- reconstruction de la projection


def rebuild_days(session: Session, ctx: TenantContext, *, days: Sequence[date]) -> None:
    """Réécrit `daily_sales_facts` pour ces jours de vente (§ 6.1).

    Appelée **après COMMIT**, par le worker analytique, jamais depuis une requête
    HTTP. L'opération est idempotente : rejouer la même plage donne le même résultat,
    c'est le test T30. Elle purge aussi les faits devenus vides — une vente annulée ne
    laisse pas de fait fantôme, c'est le test T31.
    """
    DailySalesFactRepository(session, ctx).rebuild_days(list(days))


def day_of(session: Session, ctx: TenantContext, *, sold_at: datetime) -> date:
    """Jour de vente d'un instant, dans le fuseau de l'entreprise.

    Les retours sont rattachés au jour de la vente d'origine (§ 4.10) : c'est toujours
    `sold_at` qui décide du jour à réécrire, jamais la date du retour ni celle de
    l'annulation.
    """
    timezone = companies_service.get_timezone(session, ctx)
    return sold_at.astimezone(ZoneInfo(timezone)).date()


def today_in_company(session: Session, ctx: TenantContext) -> date:
    """Date du jour dans le fuseau de l'entreprise."""
    timezone = companies_service.get_timezone(session, ctx)
    return clock.today_in(timezone)


def period_bounds(
    session: Session, ctx: TenantContext, *, period_from: date, period_to: date
) -> tuple[datetime, datetime]:
    """Bornes instantanées d'une plage de jours, dans le fuseau de l'entreprise.

    Exposé pour la réconciliation T32, qui doit interroger deux sources — les faits,
    indexés par jour local, et le transactionnel, filtré sur des `timestamptz` — en
    parlant de la **même** période. Sans cela, le contrôle accuserait la
    reconstruction d'un écart qui ne serait qu'un décalage de fuseau.
    """
    return _bounds(period_from, period_to, companies_service.get_timezone(session, ctx))


def daily_revenue_and_margin(
    session: Session, ctx: TenantContext, *, period_from: date, period_to: date
) -> list[tuple[date, Decimal, Decimal]]:
    """`(jour, revenu net, marge brute)` pour chaque jour **ayant vendu**.

    Façade destinée au tableau de bord, qui compose plusieurs mesures et densifie
    lui-même la série : lui rendre deux `Timeseries` l'obligerait à les recoudre.
    Les jours sans vente sont absents — c'est à l'appelant de les rendre à zéro.
    """
    _check_period(period_from, period_to)
    return DailySalesFactRepository(session, ctx).daily_series(
        period_from=period_from, period_to=period_to
    )


# ------------------------------------------------- classements par métrique nommée


def product_ranking(
    session: Session,
    ctx: TenantContext,
    *,
    metric: ProductMetric,
    period_from: date,
    period_to: date,
    limit: int = 10,
) -> ProductRanking:
    """Classement des produits pour **une seule** métrique, qui se nomme en réponse.

    Aucune fusion, aucun score composite : la décision 12 l'interdit, et un « meilleur
    produit » n'existe pas. Les sept premières métriques se calculent sur les agrégats
    déjà construits ; la huitième attend les `forecasts` de la phase 09 et le dit.
    """
    _check_period(period_from, period_to)
    limit = max(1, min(limit, MAX_RANKING_LIMIT))
    label, unit = METRIC_LABELS[metric]

    if metric is ProductMetric.FUTURE_POTENTIAL:
        return _future_potential_ranking(
            session, ctx, period_from=period_from, period_to=period_to, limit=limit
        )

    repository = DailySalesFactRepository(session, ctx)
    totals = repository.product_totals(period_from=period_from, period_to=period_to)
    if not totals:
        return ProductRanking(
            metric=metric,
            metric_label=label,
            unit=unit,
            period_from=period_from,
            period_to=period_to,
            items=[],
        )

    values = _metric_values(
        session, ctx, metric=metric, totals=totals, period_from=period_from, period_to=period_to
    )
    ranked = sorted(values, key=lambda row: row[1], reverse=True)[:limit]
    return ProductRanking(
        metric=metric,
        metric_label=label,
        unit=unit,
        period_from=period_from,
        period_to=period_to,
        items=[
            ProductRankRow(product_id=product_id, product_name=name, value=rendered)
            for product_id, _, name, rendered in ranked
        ],
    )


def _future_potential_ranking(
    session: Session,
    ctx: TenantContext,
    *,
    period_from: date,
    period_to: date,
    limit: int,
) -> ProductRanking:
    """Métrique 8, lue sur les `forecasts` déjà produits par CoGes Intelligence.

    La période demandée ne s'applique pas : un potentiel futur porte sur les jours qui
    viennent, à partir de la dernière prévision produite, et la réponse le dit
    (`forecast_as_of`, `horizon_days`, `computed_at`). Aucune prévision ⇒ « données
    insuffisantes » plutôt qu'une valeur inventée (décision 13).
    """
    label, unit = METRIC_LABELS[ProductMetric.FUTURE_POTENTIAL]
    potential = intelligence_serving.future_potential(session, ctx)
    if potential is None:
        reason = (
            "CoGes Intelligence est désactivée pour cette entreprise."
            if not intelligence_serving.is_enabled(session, ctx)
            else "Données insuffisantes : aucune prévision n'a encore été produite."
        )
        return ProductRanking(
            metric=ProductMetric.FUTURE_POTENTIAL,
            metric_label=label,
            unit=unit,
            period_from=period_from,
            period_to=period_to,
            unavailable_reason=reason,
            items=[],
        )
    ranked = sorted(potential.rows, key=lambda row: Decimal(row.value), reverse=True)[:limit]
    return ProductRanking(
        metric=ProductMetric.FUTURE_POTENTIAL,
        metric_label=label,
        unit=unit,
        period_from=period_from,
        period_to=period_to,
        computed_at=potential.computed_at,
        forecast_as_of=potential.as_of,
        horizon_days=potential.horizon_days,
        items=[
            ProductRankRow(
                product_id=row.product_id,
                product_name=row.product_name,
                value=row.value,
                lower=row.lower,
                upper=row.upper,
                model_name=row.model_name,
                model_version=row.model_version,
            )
            for row in ranked
        ],
    )


def _metric_values(
    session: Session,
    ctx: TenantContext,
    *,
    metric: ProductMetric,
    totals: list[dict[str, Any]],
    period_from: date,
    period_to: date,
) -> list[tuple[UUID, Decimal, str, str]]:
    """`(product_id, valeur de tri, nom, valeur affichée)` pour chaque produit."""
    days = (period_to - period_from).days + 1

    if metric is ProductMetric.REVENUE:
        return [_money(row, row["net_revenue"]) for row in totals]
    if metric is ProductMetric.MARGIN:
        return [_money(row, row["margin"]) for row in totals]
    if metric is ProductMetric.QUANTITY:
        return [_units(row, row["net_qty_sold"]) for row in totals]
    if metric is ProductMetric.FREQUENCY:
        # Nombre de ventes distinctes contenant le produit : « vendu souvent », qui
        # n'est pas « beaucoup vendu » (§ 7 de l'Architecture).
        return [
            (
                row["product_id"],
                Decimal(row["sale_count"]),
                row["product_name"],
                str(row["sale_count"]),
            )
            for row in totals
        ]
    if metric is ProductMetric.VELOCITY:
        return [_units(row, row["net_qty_sold"] / days) for row in totals]
    if metric is ProductMetric.ROTATION:
        return _rotation(session, ctx, totals=totals, period_from=period_from, period_to=period_to)
    return _demand_trend(session, ctx, period_from=period_from, period_to=period_to, days=days)


def _money(row: dict[str, Any], value: Decimal) -> tuple[UUID, Decimal, str, str]:
    rounded = to_amount(value)
    return row["product_id"], rounded, row["product_name"], serialize(rounded)


def _units(row: dict[str, Any], value: Decimal) -> tuple[UUID, Decimal, str, str]:
    rounded = to_quantity(value)
    return row["product_id"], rounded, row["product_name"], serialize(rounded)


def _rotation(
    session: Session,
    ctx: TenantContext,
    *,
    totals: list[dict[str, Any]],
    period_from: date,
    period_to: date,
) -> list[tuple[UUID, Decimal, str, str]]:
    """Quantité écoulée rapportée au **stock moyen détenu** sur la période.

    Le stock moyen est reconstitué depuis le journal, fin de journée par fin de
    journée (ADR 0033) : le stock courant seul donnerait une rotation absurde pour un
    article écoulé puis réapprovisionné.

    Un produit dont le stock moyen est nul est **écarté** plutôt que rendu à zéro : sa
    rotation n'est pas faible, elle est indéfinie, et une division par zéro ne se
    présente pas comme un classement.
    """
    timezone = companies_service.get_timezone(session, ctx)
    averages = inventory_service.average_on_hand(
        session,
        ctx,
        product_ids=[row["product_id"] for row in totals],
        period_from=period_from,
        period_to=period_to,
        timezone=timezone,
    )
    rows: list[tuple[UUID, Decimal, str, str]] = []
    for row in totals:
        average = averages.get(row["product_id"], Decimal("0"))
        if average <= 0:
            continue
        turns = to_quantity(row["net_qty_sold"] / average)
        rows.append((row["product_id"], turns, row["product_name"], serialize(turns)))
    return rows


def _demand_trend(
    session: Session,
    ctx: TenantContext,
    *,
    period_from: date,
    period_to: date,
    days: int,
) -> list[tuple[UUID, Decimal, str, str]]:
    """Variation de la vélocité entre les deux moitiés de la période, en pourcentage.

    « La demande du produit G progresse de 18 % par rapport au mois précédent » — les
    deux fenêtres doivent être comparables, donc de même longueur. Une période d'un
    seul jour n'a pas deux moitiés : le classement est alors vide.

    Un produit absent de la première moitié n'a pas de progression **mesurable** : une
    variation par rapport à zéro est infinie, pas forte. Il est écarté, et le dire en
    l'écartant vaut mieux que d'afficher un pourcentage inventé.
    """
    half = days // 2
    if half == 0:
        return []
    repository = DailySalesFactRepository(session, ctx)
    early_to = period_from + timedelta(days=half - 1)
    late_from = period_to - timedelta(days=half - 1)

    early = {
        row["product_id"]: row["net_qty_sold"]
        for row in repository.product_totals(period_from=period_from, period_to=early_to)
    }
    rows: list[tuple[UUID, Decimal, str, str]] = []
    for row in repository.product_totals(period_from=late_from, period_to=period_to):
        before = early.get(row["product_id"], Decimal("0"))
        if before <= 0:
            continue
        change = to_amount((row["net_qty_sold"] - before) / before * 100)
        rows.append((row["product_id"], change, row["product_name"], serialize(change)))
    return rows


# ------------------------------------------------------------- séries temporelles


def timeseries(
    session: Session,
    ctx: TenantContext,
    *,
    measure: TimeseriesMeasure,
    period_from: date,
    period_to: date,
) -> Timeseries:
    """Série journalière d'une mesure nommée, jours creux rendus à zéro."""
    _check_period(period_from, period_to)
    rows = DailySalesFactRepository(session, ctx).daily_series(
        period_from=period_from, period_to=period_to
    )
    index = {
        day: (revenue if measure is TimeseriesMeasure.REVENUE else margin)
        for day, revenue, margin in rows
    }
    label = SERIES_LABELS[measure]

    points: list[TimeseriesPoint] = []
    day = period_from
    while day <= period_to:
        points.append(TimeseriesPoint(day=day, value=to_amount(index.get(day, Decimal("0")))))
        day += timedelta(days=1)
    return Timeseries(
        measure=measure,
        measure_label=label,
        period_from=period_from,
        period_to=period_to,
        points=points,
    )


#: Lignes de « Ce qui s'est passé » sur la fiche d'un article.
HISTORY_SIZE = 30


def product_history(
    session: Session, ctx: TenantContext, product_id: UUID, *, limit: int = HISTORY_SIZE
) -> ProductHistory:
    """Historique d'un article en phrases (écran 08, ADR 0071).

    Composé ici parce que Restitution peut lire toutes les façades : Inventory donne les
    mouvements, Sales le client derrière une vente ou un retour, Suppliers le nom du
    fournisseur d'une livraison. Un article d'une autre entreprise donne 404.
    """
    products_service.get_product(session, ctx, product_id)
    movements, _ = inventory_service.list_movements(
        session, ctx, page=1, page_size=limit, product_id=product_id
    )
    customers = sales_service.customer_names_of_lines(
        session,
        ctx,
        sale_item_ids=[m.ref_id for m in movements if m.ref_type == "sale_item" and m.ref_id],
        return_item_ids=[
            m.ref_id for m in movements if m.ref_type == "sale_return_item" and m.ref_id
        ],
    )
    suppliers = suppliers_service.names_by_ids(
        session, ctx, [m.supplier_id for m in movements if m.supplier_id is not None]
    )

    def counterparty(movement: Any) -> str | None:
        if movement.supplier_id is not None:
            return suppliers.get(movement.supplier_id)
        if movement.ref_id is not None:
            return customers.get(movement.ref_id)
        return None

    zone = ZoneInfo(companies_service.get_timezone(session, ctx))
    now = clock.now_in(zone.key)
    month_start = datetime.combine(now.date().replace(day=1), time.min, tzinfo=zone)
    return ProductHistory(
        product_id=product_id,
        month_sold_qty=to_quantity(
            inventory_service.net_sold(session, ctx, product_id, since=month_start, until=now)
        ),
        month_days=now.day,
        items=[
            ProductHistoryItem(
                movement_id=movement.id,
                occurred_at=movement.occurred_at,
                type=movement.type,
                reason_code=movement.reason_code,
                qty_delta=movement.qty_delta,
                counterparty=counterparty(movement),
                is_reversal=movement.reversal_of_movement_id is not None,
            )
            for movement in movements
        ],
    )


# ------------------------------------------- clients et fournisseurs (écrans 13 à 16)
#
# Composés ici parce que Restitution peut lire toutes les façades (ADR 0030) : Customers
# et Suppliers donnent les personnes, Finance ce qu'elles doivent et ce qu'elles ont
# payé, Sales les visites et les achats, Inventory et Products les articles livrés. La
# liste se classe en mémoire : une boutique compte quelques centaines de personnes
# (ADR 0072). Sans le droit `debts:read`, aucun montant dû ne sort.

MONEY_PERMISSION = "debts:read"
_EPOCH = datetime.min.replace(tzinfo=ZoneInfo("UTC"))


def _month_start(session: Session, ctx: TenantContext) -> datetime:
    zone = ZoneInfo(companies_service.get_timezone(session, ctx))
    now = clock.now_in(zone.key)
    return datetime.combine(now.date().replace(day=1), time.min, tzinfo=zone)


def _page(rows: Sequence[Any], page: int, page_size: int) -> list[Any]:
    return list(rows[(page - 1) * page_size : page * page_size])


def list_people(
    session: Session,
    ctx: TenantContext,
    *,
    kind: str,
    owing: bool = False,
    search: str | None = None,
    page: int = 1,
    page_size: int = PEOPLE_PAGE_SIZE,
) -> PeoplePage:
    """Liste de l'écran 13 : qui doit d'abord (le plus gros montant), puis la dernière
    visite ou livraison la plus récente, puis le nom ; jamais venu à la fin."""
    money = ctx.has_permission(MONEY_PERMISSION)
    customers, customer_count = customers_service.directory(
        session, ctx, search=search if kind == "customer" else None
    )
    suppliers, supplier_count = suppliers_service.directory(
        session, ctx, search=search if kind == "supplier" else None
    )
    people: Sequence[Any] = customers if kind == "customer" else suppliers
    debts = finance_service.debt_summaries(session, ctx, kind)
    last_seen: dict[UUID, datetime] = (
        sales_service.last_sale_at_by_customer(session, ctx)
        if kind == "customer"
        else {party_id: summary.last_at for party_id, summary in debts.items()}
    )
    zero = Decimal("0")

    def owed(person_id: UUID) -> Decimal:
        summary = debts.get(person_id)
        return summary.owed if summary else zero

    rows = [person for person in people if not owing or owed(person.id) > 0]
    rows.sort(
        key=lambda person: (
            -(owed(person.id) if money else zero),
            last_seen.get(person.id) is None,
            -(last_seen.get(person.id, _EPOCH) - _EPOCH).total_seconds(),
            person.name.casefold(),
        )
    )
    owing_people = [person for person in people if owed(person.id) > 0]

    def row(person: Any) -> PersonRow:
        summary = debts.get(person.id)
        return PersonRow(
            id=person.id,
            name=person.name,
            phone=person.phone,
            owed=to_amount(owed(person.id)) if money else None,
            owed_since=summary.oldest_open_at if money and summary else None,
            due_date=summary.nearest_due if money and summary else None,
            last_seen_at=last_seen.get(person.id),
        )

    return PeoplePage(
        items=[row(person) for person in _page(rows, page, page_size)],
        page=page,
        page_size=page_size,
        total=len(rows),
        owing_count=len(owing_people) if money else None,
        owed_total=to_amount(sum((owed(p.id) for p in owing_people), zero)) if money else None,
        customer_count=customer_count,
        supplier_count=supplier_count,
    )


def customer_sheet(session: Session, ctx: TenantContext, customer_id: UUID) -> CustomerSheet:
    """Tuiles de la fiche client. Un client d'une autre entreprise donne 404."""
    customer = customers_service.get_customer(session, ctx, customer_id)
    money = ctx.has_permission(MONEY_PERMISSION)
    summary = finance_service.debt_summaries(session, ctx, "customer").get(customer_id)
    month_total, visits, last_visit = sales_service.customer_totals_since(
        session, ctx, customer_id, _month_start(session, ctx)
    )
    return CustomerSheet(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        created_at=customer.created_at,
        owed=to_amount(summary.owed if summary else Decimal("0")) if money else None,
        owed_since=summary.oldest_open_at if money and summary else None,
        month_total=to_amount(month_total),
        month_visits=visits,
        last_visit_at=last_visit,
    )


def _names(session: Session, ctx: TenantContext, product_ids: Sequence[UUID]) -> dict[UUID, Any]:
    return products_service.get_summaries(session, ctx, list(set(product_ids)))


def customer_sales(
    session: Session,
    ctx: TenantContext,
    customer_id: UUID,
    *,
    page: int = 1,
    page_size: int = PEOPLE_PAGE_SIZE,
) -> CustomerSalePage:
    """« Ses achats » : les ventes du client, la plus récente d'abord, sans brouillon."""
    customers_service.get_customer(session, ctx, customer_id)
    sales, total, returned = sales_service.list_sales(
        session,
        ctx,
        page=page,
        page_size=page_size,
        customer_id=customer_id,
        include_drafts=False,
    )
    sale_ids = [sale.id for sale in sales]
    products = sales_service.product_ids_by_sale(session, ctx, sale_ids)
    summaries = _names(session, ctx, [pid for ids in products.values() for pid in ids])
    statuses = finance_service.debt_statuses_for_sales(session, ctx, sale_ids)

    def names(sale_id: UUID) -> list[str]:
        ids = products.get(sale_id, [])
        return [summaries[pid].name for pid in ids if pid in summaries][:NAMED_ITEMS]

    return CustomerSalePage(
        items=[
            CustomerSaleRow(
                sale_id=sale.id,
                sale_no=sale.sale_no,
                sold_at=sale.sold_at,
                status=sale.status,
                total=to_amount(sale.total),
                balance=to_amount(sale.total - sale.paid_total),
                debt_status=statuses.get(sale.id),
                has_returns=sale.id in returned,
                item_names=names(sale.id),
                item_count=len(products.get(sale.id, [])),
            )
            for sale in sales
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


def _payment_rows(
    rows: Sequence[finance_service.PersonPayment], sale_numbers: dict[UUID, str]
) -> list[PersonPaymentRow]:
    result = []
    for row in rows:
        sale_id = row.payment.sale_id or row.debt_sale_id
        result.append(
            PersonPaymentRow(
                payment_id=row.payment.id,
                paid_at=row.payment.paid_at,
                amount=to_amount(row.payment.amount),
                method=row.payment.method,
                on_debt=row.debt_id is not None,
                sale_id=sale_id,
                sale_no=sale_numbers.get(sale_id) if sale_id else None,
                debt_id=row.debt_id,
                debt_created_at=row.debt_created_at,
            )
        )
    return result


def customer_payments(
    session: Session,
    ctx: TenantContext,
    customer_id: UUID,
    *,
    page: int = 1,
    page_size: int = PEOPLE_PAGE_SIZE,
) -> PersonPaymentPage:
    """« Ses paiements » : payé à la vente ou sur une dette, le plus récent d'abord."""
    customers_service.get_customer(session, ctx, customer_id)
    rows, total = finance_service.person_payments_page(
        session,
        ctx,
        customer_id=customer_id,
        sale_ids=sales_service.sale_ids_of_customer(session, ctx, customer_id),
        page=page,
        page_size=page_size,
    )
    sale_ids = {sale_id for row in rows if (sale_id := row.payment.sale_id or row.debt_sale_id)}
    numbers = sales_service.sale_numbers(session, ctx, list(sale_ids))
    return PersonPaymentPage(
        items=_payment_rows(rows, numbers), page=page, page_size=page_size, total=total
    )


def supplier_sheet(session: Session, ctx: TenantContext, supplier_id: UUID) -> SupplierSheet:
    """Tuiles de la fiche fournisseur. Un fournisseur d'une autre entreprise donne 404."""
    supplier = suppliers_service.get_supplier(session, ctx, supplier_id)
    money = ctx.has_permission(MONEY_PERMISSION)
    summary = finance_service.debt_summaries(session, ctx, "supplier").get(supplier_id)
    month_total, deliveries = finance_service.supplier_totals_since(
        session, ctx, supplier_id, _month_start(session, ctx)
    )
    lines = inventory_service.delivery_lines(
        session, ctx, finance_service.supplier_debt_ids(session, ctx, supplier_id)
    )
    # Ce qu'il livre : les articles des livraisons, les plus livrés (en valeur) d'abord.
    value: dict[UUID, Decimal] = {}
    for delivery in lines.values():
        for line in delivery:
            value[line.product_id] = value.get(line.product_id, Decimal("0")) + (
                line.qty * line.unit_cost
            )
    ranked = sorted(value, key=lambda pid: (-value[pid], str(pid)))
    summaries = _names(session, ctx, ranked)
    named = [summaries[pid].name for pid in ranked if pid in summaries]
    return SupplierSheet(
        id=supplier.id,
        name=supplier.name,
        phone=supplier.phone,
        address=supplier.address,
        created_at=supplier.created_at,
        owed=to_amount(summary.owed if summary else Decimal("0")) if money else None,
        due_date=summary.nearest_due if money and summary else None,
        month_total=to_amount(month_total) if money else None,
        month_deliveries=deliveries,
        product_names=named[:SUPPLIER_NAMED_PRODUCTS],
        product_count=len(named),
    )


def supplier_deliveries(
    session: Session,
    ctx: TenantContext,
    supplier_id: UUID,
    *,
    page: int = 1,
    page_size: int = PEOPLE_PAGE_SIZE,
) -> SupplierDeliveryPage:
    """« Ses livraisons » : chaque dette du fournisseur, la plus récente d'abord."""
    suppliers_service.get_supplier(session, ctx, supplier_id)
    debts, total = finance_service.supplier_debts_page(
        session, ctx, supplier_id, page=page, page_size=page_size
    )
    lines = inventory_service.delivery_lines(session, ctx, [debt.id for debt in debts])
    summaries = _names(session, ctx, [line.product_id for rows in lines.values() for line in rows])

    def line_rows(debt_id: UUID) -> list[DeliveryLineRow]:
        return [
            DeliveryLineRow(
                product_id=line.product_id,
                name=summaries[line.product_id].name,
                qty=to_quantity(line.qty),
                unit=summaries[line.product_id].unit,
            )
            for line in lines.get(debt_id, [])
            if line.product_id in summaries
        ][:NAMED_ITEMS]

    return SupplierDeliveryPage(
        items=[
            SupplierDeliveryRow(
                debt_id=debt.id,
                created_at=debt.created_at,
                total=to_amount(debt.principal),
                balance=to_amount(debt.balance),
                status=debt.status,
                due_date=debt.due_date,
                lines=line_rows(debt.id),
                line_count=len(lines.get(debt.id, [])),
            )
            for debt in debts
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


def supplier_payments(
    session: Session,
    ctx: TenantContext,
    supplier_id: UUID,
    *,
    page: int = 1,
    page_size: int = PEOPLE_PAGE_SIZE,
) -> PersonPaymentPage:
    """« Vos paiements » : ce que vous lui avez versé, le plus récent d'abord."""
    suppliers_service.get_supplier(session, ctx, supplier_id)
    rows, total = finance_service.person_payments_page(
        session, ctx, supplier_id=supplier_id, page=page, page_size=page_size
    )
    return PersonPaymentPage(
        items=_payment_rows(rows, {}), page=page, page_size=page_size, total=total
    )
