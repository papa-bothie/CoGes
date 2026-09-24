"""Façade de services du module Analytics.

Compose, ne calcule pas. Chaque mesure vient de la façade du module qui la possède :
Sales pour le revenu et le coût des ventes, Expenses pour les charges, Finance pour
la trésorerie et les encours, Companies pour le fuseau.

Aucune écriture, aucun audit, aucun événement : une lecture ne change rien.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ValidationFailedError
from app.core.money import amount as to_amount
from app.core.tenancy import TenantContext
from app.modules.analytics.schemas import (
    DAILY_SERIES_DAYS,
    MAX_PERIOD_DAYS,
    DailyCashPoint,
    FinanceOverview,
)
from app.modules.companies import service as companies_service
from app.modules.expenses import service as expenses_service
from app.modules.finance import service as finance_service
from app.modules.sales import service as sales_service


class PeriodInvertedError(ValidationFailedError):
    code = "period_inverted"
    default_message = "La date de début doit précéder la date de fin."


class PeriodTooLongError(ValidationFailedError):
    code = "period_too_long"
    default_message = f"La période ne peut pas dépasser {MAX_PERIOD_DAYS} jours."


def _bounds(period_from: date, period_to: date) -> tuple[datetime, datetime]:
    """Bornes instantanées d'une plage de jours, inclusives des deux côtés.

    Les dates sont saisies par un gérant, les colonnes sont des `timestamptz` : le
    dernier jour doit aller jusqu'à sa dernière seconde, sans quoi les
    encaissements de l'après-midi disparaîtraient du total.
    """
    if period_from > period_to:
        raise PeriodInvertedError(
            details={"from": period_from.isoformat(), "to": period_to.isoformat()}
        )
    if (period_to - period_from).days + 1 > MAX_PERIOD_DAYS:
        raise PeriodTooLongError(details={"max_days": MAX_PERIOD_DAYS})

    start = datetime.combine(period_from, time.min, tzinfo=UTC)
    end = datetime.combine(period_to, time.max, tzinfo=UTC)
    return start, end


def _daily_series(
    session: Session,
    ctx: TenantContext,
    *,
    period_from: date,
    period_to: date,
) -> list[DailyCashPoint]:
    """Trente derniers jours de la période, jours sans mouvement compris.

    Les jours vides sont rendus à zéro plutôt qu'omis : une courbe trouée se lit
    comme une absence de données, pas comme une caisse immobile.
    """
    first_day = max(period_from, period_to - timedelta(days=DAILY_SERIES_DAYS - 1))
    start, end = _bounds(first_day, period_to)
    timezone = companies_service.get_timezone(session, ctx)

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
    start, end = _bounds(period_from, period_to)

    cash = finance_service.cash_summary(session, ctx, period_from=start, period_to=end)
    revenue = sales_service.revenue_totals(session, ctx, period_from=start, period_to=end)
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
        sale_count=int(revenue["sale_count"]),
        receivables_open=to_amount(debts["customer"]),
        payables_open=to_amount(debts["supplier"]),
        daily=_daily_series(session, ctx, period_from=period_from, period_to=period_to),
    )
