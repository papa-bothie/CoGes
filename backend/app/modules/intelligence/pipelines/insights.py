"""Étape 07 : insights explicables ⇒ `insights`, et alerte des insights critiques.

Chaque insight nomme sa métrique et porte son évidence (séries, seuils, écarts,
période) : l'écran justifie l'alerte sans relancer un calcul (§ 4.12). La clé de
déduplication est stable sur la semaine — un rejeu met à jour, il ne republie pas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.customers import service as customers_service
from app.modules.finance import service as finance_service
from app.modules.intelligence.estimators import anomaly
from app.modules.intelligence.estimators.pareto import abc_classes
from app.modules.intelligence.features.builder import (
    MIN_HISTORY_DAYS,
    MIN_SOLD_DAYS,
    SOLD_DAYS_WINDOW,
)
from app.modules.intelligence.models import MlFeatureSnapshot
from app.modules.intelligence.pipelines import templates
from app.modules.intelligence.pipelines.common import valid_until, week_version
from app.modules.intelligence.pipelines.infer import InferRun
from app.modules.intelligence.repository import InsightRepository
from app.modules.intelligence.schemas import InsightSeverity, InsightType
from app.modules.notifications import service as notifications_service
from app.modules.notifications.schemas import NotificationType

# --- Seuils des règles (ADR 0035). Ils figurent aussi dans l'évidence de chaque insight.
STOCKOUT_WARNING_DAYS = 7
STOCKOUT_CRITICAL_DAYS = 3
SLOW_MOVER_COVER_DAYS = Decimal(90)
SPIKE_Z = 3.0
SPIKE_MIN_QTY = Decimal(3)
SPIKE_MIN_OBSERVATIONS = 14
MARGIN_DROP_POINTS = Decimal("0.05")
OVERDUE_WARNING_DAYS = 7
OVERDUE_CRITICAL_DAYS = 30

ABC_MODEL = ("abc_pareto", "1")
ZSCORE_MODEL = ("zscore_28", "1")


@dataclass
class InsightRun:
    emitted: dict[str, int] = field(default_factory=dict)
    resolved: int = 0
    notified: int = 0


@dataclass(frozen=True)
class Draft:
    insight_type: InsightType
    severity: InsightSeverity
    title: str
    body: str
    entity_table: str | None
    entity_id: UUID | None
    evidence: dict[str, Any]
    dedupe_key: str
    model: tuple[str, str] | None = None


def _product_evidence(
    metric: str, value: str, unit: str, as_of: date, **extra: Any
) -> dict[str, Any]:
    return {
        "metric_name": metric,
        "value": value,
        "unit": unit,
        "as_of": as_of.isoformat(),
        **extra,
    }


def _d(features: dict[str, Any], key: str) -> Decimal | None:
    raw = features.get(key)
    return Decimal(str(raw)) if raw is not None else None


def build_drafts(
    session: Session,
    ctx: TenantContext,
    *,
    as_of: date,
    snapshots: list[MlFeatureSnapshot],
    inferred: InferRun,
) -> list[Draft]:
    """Toutes les règles de la V1, sur les photographies figées et les prévisions."""
    week = week_version(as_of)
    drafts: list[Draft] = []
    by_product = {snapshot.product_id: snapshot.features for snapshot in snapshots}

    # insufficient_history — « données insuffisantes » est un fait, pas un silence.
    for product_id, features in by_product.items():
        if features.get("sufficient"):
            continue
        history_days = int(features.get("history_days", 0))
        sold_days = int(features.get("sold_days_60d", 0))
        title, body = templates.insufficient_history(
            str(features.get("product_name", "Produit")), history_days, sold_days
        )
        drafts.append(
            Draft(
                InsightType.INSUFFICIENT_HISTORY,
                InsightSeverity.INFO,
                title,
                body,
                "products",
                product_id,
                _product_evidence(
                    templates.METRIC_HISTORY,
                    str(history_days),
                    "jour",
                    as_of,
                    sold_days_60d=sold_days,
                    thresholds={
                        "min_history_days": MIN_HISTORY_DAYS,
                        "min_sold_days": MIN_SOLD_DAYS,
                        "sold_days_window": SOLD_DAYS_WINDOW,
                    },
                    first_sale_day=features.get("first_sale_day"),
                    insufficient_data=True,
                ),
                f"insufficient_history:{product_id}",
            )
        )

    # stockout_risk — depuis la prévision de rupture de l'étape 06.
    for product_id, stockout in inferred.stockouts.items():
        if stockout.days > STOCKOUT_WARNING_DAYS:
            continue
        severity = (
            InsightSeverity.CRITICAL
            if stockout.days <= STOCKOUT_CRITICAL_DAYS
            else InsightSeverity.WARNING
        )
        features = by_product[product_id]
        when = as_of + timedelta(days=stockout.days)
        title, body = templates.stockout_risk(
            str(features.get("product_name", "Produit")),
            stockout.days,
            stockout.on_hand,
            when,
            stockout.daily_demand,
        )
        drafts.append(
            Draft(
                InsightType.STOCKOUT_RISK,
                severity,
                title,
                body,
                "products",
                product_id,
                _product_evidence(
                    templates.METRIC_STOCKOUT,
                    str(stockout.days),
                    "jour",
                    as_of,
                    stockout_date=when.isoformat(),
                    on_hand=format(stockout.on_hand, "f"),
                    forecast_daily_demand=format(stockout.daily_demand, "f"),
                    uncertainty={
                        "lower": str(stockout.earliest),
                        "upper": str(stockout.latest) if stockout.latest is not None else None,
                        "level": stockout.level,
                    },
                    thresholds={
                        "warning_days": STOCKOUT_WARNING_DAYS,
                        "critical_days": STOCKOUT_CRITICAL_DAYS,
                    },
                ),
                f"stockout_risk:{product_id}:{week}",
                (stockout.model_name, stockout.model_version),
            )
        )

    # slow_mover — classe C de Pareto sur le chiffre d'affaires, stock immobile.
    revenue = {pid: _d(f, "revenue_28d") or Decimal(0) for pid, f in by_product.items()}
    classes = abc_classes(revenue)
    for product_id, features in by_product.items():
        on_hand = _d(features, "on_hand")
        avg_on_hand = _d(features, "avg_on_hand_28d")
        velocity = _d(features, "velocity_28d") or Decimal(0)
        cover = _d(features, "days_of_cover")
        if (
            classes.get(product_id) != "C"
            or on_hand is None
            or on_hand <= 0
            or avg_on_hand is None
            or avg_on_hand <= 0
            or int(features.get("stockout_days_28d", 0)) > 0
            or (cover is not None and cover <= SLOW_MOVER_COVER_DAYS)
        ):
            continue
        title, body = templates.slow_mover(
            str(features.get("product_name", "Produit")), velocity, on_hand, cover
        )
        drafts.append(
            Draft(
                InsightType.SLOW_MOVER,
                InsightSeverity.INFO,
                title,
                body,
                "products",
                product_id,
                _product_evidence(
                    templates.METRIC_VELOCITY,
                    format(velocity, "f"),
                    "unité/jour",
                    as_of,
                    period_days=28,
                    on_hand=format(on_hand, "f"),
                    days_of_cover=format(cover, "f") if cover is not None else None,
                    abc_class="C",
                    abc_metric=templates.METRIC_REVENUE_28D,
                    thresholds={"min_cover_days": str(SLOW_MOVER_COVER_DAYS)},
                ),
                f"slow_mover:{product_id}:{week}",
                ABC_MODEL,
            )
        )

    # demand_spike — z-score du jour contre les 28 jours précédents hors ruptures.
    for product_id, features in by_product.items():
        observed = _d(features, "qty_1d") or Decimal(0)
        mean, std = float(features["mean_prior_28d"]), float(features["std_prior_28d"])
        if (
            not features.get("sufficient")
            or int(features.get("observable_prior_28d", 0)) < SPIKE_MIN_OBSERVATIONS
            or observed < SPIKE_MIN_QTY
        ):
            continue
        z = anomaly.zscore(float(observed), mean, std)
        if z is None or z < SPIKE_Z:
            continue
        title, body = templates.demand_spike(
            str(features.get("product_name", "Produit")),
            as_of,
            observed,
            str(features["mean_prior_28d"]),
            z,
        )
        drafts.append(
            Draft(
                InsightType.DEMAND_SPIKE,
                InsightSeverity.WARNING,
                title,
                body,
                "products",
                product_id,
                _product_evidence(
                    templates.METRIC_QUANTITY,
                    format(observed, "f"),
                    "unité",
                    as_of,
                    mean_prior_28d=features["mean_prior_28d"],
                    std_prior_28d=features["std_prior_28d"],
                    zscore=f"{z:.2f}",
                    thresholds={"z": SPIKE_Z, "min_qty": str(SPIKE_MIN_QTY)},
                ),
                f"demand_spike:{product_id}:{as_of.isoformat()}",
                ZSCORE_MODEL,
            )
        )

    # margin_drop — taux de marge des 7 derniers jours contre les 28 derniers.
    for product_id, features in by_product.items():
        rate_7d = _d(features, "margin_rate_7d")
        rate_28d = _d(features, "margin_rate_28d")
        if rate_7d is None or rate_28d is None or rate_7d > rate_28d - MARGIN_DROP_POINTS:
            continue
        title, body = templates.margin_drop(
            str(features.get("product_name", "Produit")), rate_7d, rate_28d
        )
        drafts.append(
            Draft(
                InsightType.MARGIN_DROP,
                InsightSeverity.WARNING,
                title,
                body,
                "products",
                product_id,
                _product_evidence(
                    templates.METRIC_MARGIN_RATE,
                    format(rate_7d, "f"),
                    "ratio",
                    as_of,
                    margin_rate_28d=format(rate_28d, "f"),
                    margin_7d=features.get("margin_7d"),
                    margin_28d=features.get("margin_28d"),
                    revenue_7d=features.get("revenue_7d"),
                    revenue_28d=features.get("revenue_28d"),
                    thresholds={"drop_points": format(MARGIN_DROP_POINTS, "f")},
                ),
                f"margin_drop:{product_id}:{week}",
            )
        )

    drafts.extend(_overdue_drafts(session, ctx, as_of=as_of, week=week))
    return drafts


def _overdue_drafts(session: Session, ctx: TenantContext, *, as_of: date, week: str) -> list[Draft]:
    """debt_overdue — créances clients échues depuis plus d'une semaine, par client."""
    per_customer: dict[UUID, tuple[Decimal, date, int]] = {}
    for debt in finance_service.debts_due(session, ctx, on=as_of):
        if debt.party_type != "customer" or debt.customer_id is None or debt.due_date is None:
            continue
        if (as_of - debt.due_date).days <= OVERDUE_WARNING_DAYS:
            continue
        balance, oldest, count = per_customer.get(debt.customer_id, (Decimal(0), debt.due_date, 0))
        per_customer[debt.customer_id] = (
            balance + debt.balance,
            min(oldest, debt.due_date),
            count + 1,
        )

    names = customers_service.names_by_ids(session, ctx, list(per_customer))
    drafts: list[Draft] = []
    for customer_id, (balance, oldest, count) in per_customer.items():
        days = (as_of - oldest).days
        title, body = templates.debt_overdue(
            names.get(customer_id, "Client"), days, balance, oldest
        )
        drafts.append(
            Draft(
                InsightType.DEBT_OVERDUE,
                InsightSeverity.CRITICAL
                if days > OVERDUE_CRITICAL_DAYS
                else InsightSeverity.WARNING,
                title,
                body,
                "customers",
                customer_id,
                {
                    "metric_name": templates.METRIC_OVERDUE,
                    "value": str(days),
                    "unit": "jour",
                    "as_of": as_of.isoformat(),
                    "balance": format(balance, "f"),
                    "oldest_due_date": oldest.isoformat(),
                    "debt_count": count,
                    "thresholds": {
                        "warning_days": OVERDUE_WARNING_DAYS,
                        "critical_days": OVERDUE_CRITICAL_DAYS,
                    },
                },
                f"debt_overdue:{customer_id}:{week}",
            )
        )
    return drafts


def emit(
    session: Session,
    ctx: TenantContext,
    *,
    as_of: date,
    drafts: list[Draft],
    now: datetime,
) -> InsightRun:
    """Écrit les insights, résout ceux qui ne sont plus vrais, alerte les critiques.

    Seul `insufficient_history` se résout de lui-même quand il n'est plus réémis :
    c'est le seul dont l'absence prouve la disparition du problème. Les autres
    s'éteignent par `valid_until`, à la fin de la semaine suivante.
    """
    run = InsightRun()
    repository = InsightRepository(session, ctx)
    expires = valid_until(as_of)
    kept_insufficient: list[str] = []

    for draft in drafts:
        insight_id, _ = repository.upsert(
            {
                "insight_type": draft.insight_type.value,
                "severity": draft.severity.value,
                "title": draft.title,
                "body": draft.body,
                "entity_table": draft.entity_table,
                "entity_id": draft.entity_id,
                "evidence": draft.evidence,
                "dedupe_key": draft.dedupe_key,
                "model_name": draft.model[0] if draft.model else None,
                "model_version": draft.model[1] if draft.model else None,
                "valid_until": None
                if draft.insight_type is InsightType.INSUFFICIENT_HISTORY
                else expires,
            }
        )
        run.emitted[draft.insight_type.value] = run.emitted.get(draft.insight_type.value, 0) + 1
        if draft.insight_type is InsightType.INSUFFICIENT_HISTORY:
            kept_insufficient.append(draft.dedupe_key)

        # Un insight critique crée une notification ; l'inverse n'existe pas (§ 4.12).
        # L'entité de la notification est l'insight : un rejeu ne réveille personne
        # une seconde fois dans la fenêtre de déduplication.
        if draft.severity is InsightSeverity.CRITICAL:
            run.notified += notifications_service.notify(
                session,
                ctx,
                notification_type=NotificationType.INSIGHT_CRITICAL,
                title=draft.title,
                body=draft.body,
                entity_id=str(insight_id),
                data={"insight_id": str(insight_id), "insight_type": draft.insight_type.value},
            )

    run.resolved = repository.resolve_live(
        insight_type=InsightType.INSUFFICIENT_HISTORY.value, keep=kept_insufficient, now=now
    )
    return run
