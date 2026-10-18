"""Façade de services du module Dashboard.

Compose et met en cache. Chaque chiffre vient de la façade du module qui le possède
(le jour en cours se lit en direct sur Sales, le passé sur les faits, ADR 0061) ; le
seul travail propre à ce module est l'assemblage, la conversion dans le fuseau de
l'entreprise et la gestion du cache court.

Le cache est **transparent** : une réponse servie depuis Redis est identique à une
réponse recalculée, à `cached` près. Redis absent ⇒ on recalcule et on sert (décision
14 et `app/core/cache.py`).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core import cache, clock
from app.core.config import get_settings
from app.core.money import amount as to_amount
from app.core.tenancy import TenantContext
from app.modules.analytics import service as analytics_service
from app.modules.companies import service as companies_service
from app.modules.customers import service as customers_service
from app.modules.dashboard.schemas import (
    ACTIVE_ALERTS,
    RECENT_SALES,
    REVENUE_TREND_DAYS,
    WATCH_STOCK,
    ActiveAlert,
    Dashboard,
    RecentSale,
    RevenuePoint,
    WatchDebt,
    WatchStock,
)
from app.modules.finance import service as finance_service
from app.modules.inventory import service as inventory_service
from app.modules.notifications import service as notifications_service
from app.modules.sales import service as sales_service

#: Nom de la clé de cache. Le `company_id` est ajouté par `app.core.cache`.
CACHE_KEY = cache.DASHBOARD_KEY


def invalidate(company_id: UUID) -> None:
    """Oublie le tableau de bord d'une entreprise.

    Appelée par les consommateurs d'événements après COMMIT : c'est
    l'« invalidation par événement » de la décision 14. Le TTL court reste le filet si
    l'invalidation échoue, et l'échec de l'invalidation elle-même est sans gravité.
    """
    cache.invalidate(company_id, CACHE_KEY)


#: Champs réservés à un droit : sans lui, ils partent à `null` (ADR 0087). La marge
#: suit `analytics:read` (ADR 0030), ce qui est dû `debts:read` (ADR 0072), la caisse
#: le droit de `/analytics/cash`, où elle se détaille.
RESTRICTED_FIELDS: dict[str, str] = {
    "estimated_margin_month": "analytics:read",
    "cash_on_hand": "analytics:read",
    "receivables_open": "debts:read",
    "receivables_customer_count": "debts:read",
    "watch_debt": "debts:read",
}


def dashboard(session: Session, ctx: TenantContext, *, use_cache: bool = True) -> Dashboard:
    """Indicateurs d'accueil de l'entreprise, cache court compris, vus par `ctx`.

    Le cache est **par entreprise** : il ne garde que ce qui est commun à tous ses
    lecteurs. Ce qui dépend de la personne — ses alertes, ce que ses droits lui
    laissent lire — est posé à chaque requête, après le cache (ADR 0087).
    """
    shared = _shared(session, ctx, use_cache=use_cache)
    return _for_viewer(session, ctx, shared)


def _shared(session: Session, ctx: TenantContext, *, use_cache: bool) -> Dashboard:
    if use_cache:
        cached = cache.get_json(ctx.company_id, CACHE_KEY)
        if cached is not None:
            # `cached` n'est pas réinjecté tel quel : Pydantic le revalide, donc une
            # entrée écrite par une version antérieure du schéma est rejetée plutôt
            # que servie à moitié.
            payload = Dashboard.model_validate(cached)
            return payload.model_copy(update={"cached": True})

    fresh = _compose(session, ctx)
    cache.set_json(
        ctx.company_id,
        CACHE_KEY,
        fresh.model_dump(mode="json"),
        ttl_seconds=get_settings().dashboard_cache_ttl_seconds,
    )
    return fresh


def _for_viewer(session: Session, ctx: TenantContext, shared: Dashboard) -> Dashboard:
    """Les alertes de la personne, et rien de ce que ses droits ne lui ouvrent pas."""
    update: dict[str, object] = {
        field: None
        for field, permission in RESTRICTED_FIELDS.items()
        if not ctx.has_permission(permission)
    }
    update["active_alerts"] = _active_alerts(session, ctx)
    return shared.model_copy(update=update)


def _compose(session: Session, ctx: TenantContext) -> Dashboard:
    """Assemble la réponse. Une seule transaction, uniquement des lectures indexées."""
    zone = ZoneInfo(companies_service.get_timezone(session, ctx))
    today = clock.now_in(zone.key).date()
    month_from = today.replace(day=1)
    trend_from = today - timedelta(days=REVENUE_TREND_DAYS - 1)

    # Le passé vient des faits, **jusqu'à hier** ; le jour en cours se calcule en direct
    # sur `sales` et `sale_items` (ADR 0061). Sans quoi le CA du jour attendrait le
    # relais d'outbox et le worker, alors que le nombre de ventes, lui, bouge déjà.
    series_from = min(trend_from, month_from)
    yesterday = today - timedelta(days=1)
    series = analytics_service.daily_revenue_and_margin(
        session, ctx, period_from=series_from, period_to=yesterday
    )

    day_start = datetime.combine(today, time.min, tzinfo=zone)
    day_end = datetime.combine(today, time.max, tzinfo=zone)
    live = sales_service.revenue_totals(session, ctx, period_from=day_start, period_to=day_end)
    revenue_today = live["net_revenue"]
    margin_today = live["net_revenue"] - live["cogs_net"]
    sales_today = int(live["sale_count"])

    revenue_month = revenue_today
    margin_month = margin_today
    by_day: dict[date, Decimal] = {today: revenue_today}
    for day, net_revenue, margin in series:
        by_day[day] = net_revenue
        if day >= month_from:
            revenue_month += net_revenue
            margin_month += margin

    debts = finance_service.open_debt_totals(session, ctx)

    return Dashboard(
        today=today,
        month_from=month_from,
        month_to=today,
        revenue_today=to_amount(revenue_today),
        revenue_month=to_amount(revenue_month),
        # « Estimée » : c'est la marge brute du § 4.10, sans charges d'exploitation.
        # La confondre avec un résultat serait le reproche de la décision 09.
        estimated_margin_month=to_amount(margin_month),
        sales_today=sales_today,
        receivables_open=to_amount(debts["customer"]),
        receivables_customer_count=finance_service.open_customer_count(session, ctx),
        stock_alert_count=inventory_service.stock_alert_count(session, ctx),
        cash_on_hand=to_amount(finance_service.cash_on_hand(session, ctx)),
        watch_stock=[
            WatchStock(
                product_id=item.product_id,
                name=item.name,
                unit=item.unit,
                qty_on_hand=item.qty_on_hand,
                status=item.status,
            )
            for item in inventory_service.stock_to_watch(session, ctx, limit=WATCH_STOCK)
        ],
        watch_debt=_watch_debt(session, ctx, today=today, zone=zone),
        revenue_trend=_trend(by_day, trend_from, today),
        recent_sales=_recent_sales(session, ctx),
        # Propres à la personne : posées par `_for_viewer`, jamais mises en cache.
        active_alerts=[],
        computed_at=clock.now_in(zone.key),
    )


def _trend(by_day: dict[date, Decimal], period_from: date, period_to: date) -> list[RevenuePoint]:
    """Courbe des trente derniers jours, jours creux à zéro.

    Une courbe trouée se lit comme une absence de données, pas comme une caisse
    immobile — même règle que la série de trésorerie de l'ADR 0030.
    """
    points: list[RevenuePoint] = []
    day = period_from
    while day <= period_to:
        points.append(RevenuePoint(day=day, net_revenue=to_amount(by_day.get(day, Decimal("0")))))
        day += timedelta(days=1)
    return points


def _recent_sales(session: Session, ctx: TenantContext) -> list[RecentSale]:
    """Cinq dernières ventes confirmées, client nommé, avec leur état de paiement."""
    sales, _, returned = sales_service.list_sales(
        session, ctx, page=1, page_size=RECENT_SALES, status="confirmed"
    )
    return [
        RecentSale(
            id=read.id,
            sale_no=read.sale_no,
            customer_name=read.customer_name,
            total=to_amount(read.total),
            sold_at=read.sold_at,
            status=read.status,
            balance=read.balance,
            debt_status=read.debt_status,
            has_returns=read.has_returns,
            returned_total=read.returned_total,
        )
        for read in sales_service.build_page(session, ctx, sales, returned)
    ]


def _watch_debt(
    session: Session, ctx: TenantContext, *, today: date, zone: ZoneInfo
) -> WatchDebt | None:
    """La plus grosse dette client, et depuis combien de jours elle court."""
    largest = finance_service.largest_open_customer_debt(session, ctx)
    if largest is None:
        return None
    name = customers_service.names_by_ids(session, ctx, [largest.customer_id]).get(
        largest.customer_id
    )
    if name is None:
        return None
    return WatchDebt(
        customer_id=largest.customer_id,
        customer_name=name,
        balance=to_amount(largest.balance),
        days=max(0, (today - largest.oldest_open_at.astimezone(zone).date()).days),
    )


def _active_alerts(session: Session, ctx: TenantContext) -> list[ActiveAlert]:
    """Alertes non lues de l'utilisateur courant — les siennes, jamais celles d'autrui."""
    items, _ = notifications_service.list_for_user(
        session, ctx, page=1, page_size=ACTIVE_ALERTS, unread_only=True
    )
    return [
        ActiveAlert(
            id=item.id,
            type=item.type,
            severity=notifications_service.severity_of(item.type),
            title=item.title,
            created_at=item.created_at,
        )
        for item in items
    ]
