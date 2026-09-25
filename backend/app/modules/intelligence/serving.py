"""Étape 09 du Diagramme 7 : servir des résultats **déjà calculés**.

Seul code d'Intelligence sur le chemin d'une requête HTTP. Il ne lit que `forecasts`
et `insights` (et le drapeau de l'entreprise), par leurs index, sans aucun calcul :
aucune lecture de `ml_feature_snapshots` — que `coges_app` ne peut d'ailleurs pas
lire (révision 0011) — ni des tables transactionnelles (**T35**). Il n'importe ni
numpy, ni pandas, ni statsmodels.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.money import serialize
from app.core.tenancy import TenantContext
from app.modules.companies import service as companies_service
from app.modules.intelligence.models import Forecast, Insight
from app.modules.intelligence.repository import ForecastRepository, InsightRepository
from app.modules.intelligence.schemas import (
    FORECAST_LABELS,
    ForecastPage,
    ForecastRead,
    ForecastType,
    FuturePotential,
    FuturePotentialRow,
    InsightPage,
    InsightRead,
    InsightSeverity,
    InsightStatus,
    InsightType,
    IntelligenceSummary,
    Uncertainty,
)

#: Horizon de la métrique 8 : la demande publiée jour par jour (étape 06).
FUTURE_POTENTIAL_HORIZON_DAYS = 14


def is_enabled(session: Session, ctx: TenantContext) -> bool:
    return companies_service.is_intelligence_enabled(session, ctx)


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else serialize(value.normalize())


def insight_read(insight: Insight) -> InsightRead:
    evidence = insight.evidence or {}
    raw_uncertainty = evidence.get("uncertainty")
    uncertainty = (
        Uncertainty(
            lower=_text(raw_uncertainty.get("lower")),
            upper=_text(raw_uncertainty.get("upper")),
            level=_text(raw_uncertainty.get("level")),
        )
        if isinstance(raw_uncertainty, dict)
        else None
    )
    return InsightRead(
        id=insight.id,
        insight_type=InsightType(insight.insight_type),
        severity=InsightSeverity(insight.severity),
        status=InsightStatus(insight.status),
        title=insight.title,
        body=insight.body,
        entity_table=insight.entity_table,
        entity_id=insight.entity_id,
        metric_name=_text(evidence.get("metric_name")),
        value=_text(evidence.get("value")),
        unit=_text(evidence.get("unit")),
        computed_at=insight.generated_at,
        model_name=insight.model_name,
        model_version=insight.model_version,
        uncertainty=uncertainty,
        insufficient_data=insight.insight_type == InsightType.INSUFFICIENT_HISTORY.value,
        evidence=evidence,
        read_at=insight.read_at,
        resolved_at=insight.resolved_at,
        valid_until=insight.valid_until,
    )


def forecast_read(forecast: Forecast) -> ForecastRead:
    kind = ForecastType(forecast.forecast_type)
    label, unit = FORECAST_LABELS[kind]
    meta = forecast.metadata_ or {}
    return ForecastRead(
        id=forecast.id,
        product_id=forecast.product_id,
        product_name=_text(meta.get("product_name")),
        forecast_type=kind,
        metric_name=label,
        unit=unit,
        as_of=forecast.as_of,
        horizon_date=forecast.horizon_date,
        value=serialize(forecast.yhat.normalize()),
        uncertainty=Uncertainty(
            lower=_decimal(forecast.yhat_lower),
            upper=_decimal(forecast.yhat_upper),
            level=_text(meta.get("uncertainty")),
        ),
        computed_at=forecast.generated_at,
        model_name=forecast.model_name,
        model_version=forecast.model_version,
    )


def list_insights(
    session: Session,
    ctx: TenantContext,
    *,
    status: InsightStatus | None,
    severity: InsightSeverity | None,
    insight_type: InsightType | None,
    page: int,
    page_size: int,
    now: datetime | None = None,
) -> InsightPage:
    """Insights vivants (ou du statut demandé), non périmés, les plus récents d'abord."""
    if not is_enabled(session, ctx):
        return InsightPage(enabled=False, items=[], page=page, page_size=page_size, total=0)
    moment = now or datetime.now(UTC)
    filters = {
        "status": status.value if status else None,
        "severity": severity.value if severity else None,
        "insight_type": insight_type.value if insight_type else None,
    }
    repository = InsightRepository(session, ctx)
    items = repository.page_visible(now=moment, page=page, page_size=page_size, **filters)
    return InsightPage(
        enabled=True,
        items=[insight_read(item) for item in items],
        page=page,
        page_size=page_size,
        total=repository.count_visible(now=moment, **filters),
    )


def list_forecasts(
    session: Session,
    ctx: TenantContext,
    *,
    product_id: UUID | None,
    forecast_type: ForecastType | None,
    page: int,
    page_size: int,
    now: datetime | None = None,
) -> ForecastPage:
    """Prévisions du dernier `as_of` produit — jamais « en direct », toujours datées."""
    empty = ForecastPage(
        enabled=False, insufficient_data=False, items=[], page=page, page_size=page_size, total=0
    )
    if not is_enabled(session, ctx):
        return empty
    repository = ForecastRepository(session, ctx)
    as_of = repository.latest_as_of()
    kind = forecast_type.value if forecast_type else None
    items: list[Forecast] = []
    total = 0
    if as_of is not None:
        items = list(
            repository.page_for(
                as_of, product_id=product_id, forecast_type=kind, page=page, page_size=page_size
            )
        )
        total = repository.count_for(as_of, product_id=product_id, forecast_type=kind)

    insufficient = False
    if product_id is not None and total == 0:
        # « Données insuffisantes » est un fait persisté par le pipeline, pas une
        # déduction de l'API : on le lit, on ne le calcule pas.
        insufficient = (
            InsightRepository(session, ctx).live_for_entity(
                insight_type=InsightType.INSUFFICIENT_HISTORY.value,
                entity_id=product_id,
                now=now or datetime.now(UTC),
            )
            is not None
        )
    return ForecastPage(
        enabled=True,
        insufficient_data=insufficient,
        items=[forecast_read(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


def summary(
    session: Session, ctx: TenantContext, *, now: datetime | None = None
) -> IntelligenceSummary:
    """Compteurs de l'écran Insights."""
    if not is_enabled(session, ctx):
        return IntelligenceSummary(
            enabled=False,
            last_as_of=None,
            computed_at=None,
            insights_by_type={},
            insights_by_severity={},
            forecast_products=0,
            insufficient_data_products=0,
        )
    moment = now or datetime.now(UTC)
    forecasts = ForecastRepository(session, ctx)
    insights = InsightRepository(session, ctx)
    as_of = forecasts.latest_as_of()
    products, computed_at = forecasts.summary(as_of) if as_of else (0, None)
    by_type = insights.live_counts(now=moment, column="insight_type")
    return IntelligenceSummary(
        enabled=True,
        last_as_of=as_of,
        computed_at=computed_at,
        insights_by_type=by_type,
        insights_by_severity=insights.live_counts(now=moment, column="severity"),
        forecast_products=products,
        insufficient_data_products=by_type.get(InsightType.INSUFFICIENT_HISTORY.value, 0),
    )


def future_potential(session: Session, ctx: TenantContext) -> FuturePotential | None:
    """Métrique 8 « potentiel futur estimé » : quantité prévue sur les 14 jours qui viennent.

    Façade pour le classement d'Analytics. `None` quand l'Intelligence est coupée ou
    n'a encore rien produit : l'appelant le dit plutôt que d'inventer une valeur.
    """
    if not is_enabled(session, ctx):
        return None
    repository = ForecastRepository(session, ctx)
    as_of = repository.latest_as_of()
    if as_of is None:
        return None
    rows = repository.demand_totals(
        as_of, horizon_to=as_of + timedelta(days=FUTURE_POTENTIAL_HORIZON_DAYS)
    )
    if not rows:
        return None
    return FuturePotential(
        as_of=as_of,
        horizon_days=FUTURE_POTENTIAL_HORIZON_DAYS,
        computed_at=max(row["generated_at"] for row in rows),
        rows=[
            FuturePotentialRow(
                product_id=row["product_id"],
                product_name=row["product_name"] or "Produit",
                value=serialize(Decimal(row["total"]).quantize(Decimal("0.001"))),
                lower=_decimal(row["lower"]),
                upper=_decimal(row["upper"]),
                model_name=row["model_name"],
                model_version=row["model_version"],
            )
            for row in rows
        ],
    )
