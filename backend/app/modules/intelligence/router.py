"""Routes HTTP de CoGes Intelligence. Aucune requête SQL, aucun calcul ici.

Lecture seule de résultats déjà produits par le pipeline ; la seule écriture est le
statut d'un insight. Intelligence coupée ⇒ 200 avec `enabled: false`, et le reste de
CoGes continue de fonctionner (Diagramme 7, « Désactivation »).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.deps import TenantSession, require_permission
from app.core.repository import MAX_PAGE_SIZE
from app.modules.intelligence import service, serving
from app.modules.intelligence.schemas import (
    ForecastPage,
    ForecastType,
    InsightPage,
    InsightRead,
    InsightSeverity,
    InsightStatus,
    InsightStatusUpdate,
    InsightType,
    IntelligenceSummary,
)

router = APIRouter(tags=["intelligence"])


@router.get("/insights", response_model=InsightPage)
def list_insights(
    tenant: Annotated[TenantSession, Depends(require_permission("insights:read"))],
    status: InsightStatus | None = None,
    severity: InsightSeverity | None = None,
    insight_type: Annotated[InsightType | None, Query(alias="type")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> InsightPage:
    """Insights vivants par défaut (nouveaux, lus, acquittés), les plus récents d'abord."""
    return serving.list_insights(
        tenant.session,
        tenant.ctx,
        status=status,
        severity=severity,
        insight_type=insight_type,
        page=page,
        page_size=page_size,
    )


@router.patch("/insights/{insight_id}", response_model=InsightRead)
def update_insight(
    insight_id: UUID,
    payload: InsightStatusUpdate,
    tenant: Annotated[TenantSession, Depends(require_permission("insights:update"))],
) -> InsightRead:
    """Lu, acquitté, écarté ou résolu. Seul `status` est modifiable (§ 4.12)."""
    return service.set_insight_status(tenant.session, tenant.ctx, insight_id, payload.status)


@router.get("/forecasts", response_model=ForecastPage)
def list_forecasts(
    tenant: Annotated[TenantSession, Depends(require_permission("insights:read"))],
    product_id: UUID | None = None,
    forecast_type: Annotated[ForecastType | None, Query(alias="type")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> ForecastPage:
    """Prévisions du dernier jour produit, datées, avec modèle et incertitude."""
    return serving.list_forecasts(
        tenant.session,
        tenant.ctx,
        product_id=product_id,
        forecast_type=forecast_type,
        page=page,
        page_size=page_size,
    )


@router.get("/intelligence/summary", response_model=IntelligenceSummary)
def intelligence_summary(
    tenant: Annotated[TenantSession, Depends(require_permission("insights:read"))],
) -> IntelligenceSummary:
    """Compteurs par type et par gravité, et produits aux données insuffisantes."""
    return serving.summary(tenant.session, tenant.ctx)
