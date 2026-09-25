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
    DailyCashPoint,
    FinanceOverview,
    ProductMetric,
    ProductRanking,
    ProductRankRow,
    Timeseries,
    TimeseriesMeasure,
    TimeseriesPoint,
)
from app.modules.companies import service as companies_service
from app.modules.expenses import service as expenses_service
from app.modules.finance import service as finance_service
from app.modules.inventory import service as inventory_service
from app.modules.sales import service as sales_service


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
    return datetime.now(ZoneInfo(timezone)).date()


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
        # « Données insuffisantes » plutôt qu'une valeur inventée (décision 13). Le
        # classement existe, il est simplement vide et dit pourquoi.
        return ProductRanking(
            metric=metric,
            metric_label=label,
            unit=unit,
            period_from=period_from,
            period_to=period_to,
            unavailable_reason=(
                "Le potentiel futur estimé vient d'un modèle de prévision, disponible en phase 09."
            ),
            items=[],
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
    label = "Chiffre d'affaires net" if measure is TimeseriesMeasure.REVENUE else "Marge brute"

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
