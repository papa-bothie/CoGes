"""Étapes 06 et 07 du Diagramme 7 : prévisions et insights, chaque nuit."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.intelligence.pipelines import run_inference
from app.workers.beat import ML_INFER
from app.workers.celery_app import celery_app
from app.workers.jobs import tracked_job
from app.workers.tasks.intelligence_common import artifact_store, run_for_company
from app.workers.tenants import each_company

logger = logging.getLogger(__name__)


@celery_app.task(name="ml_infer.infer")
@tracked_job("ml_infer.infer", ping_as=ML_INFER)
def infer(company_id: str, as_of: str | None = None) -> int:
    """Produit les prévisions et insights d'une entreprise. Renvoie le nombre de prévisions."""

    def _step(session: Session, ctx: TenantContext, day: date) -> int:
        result = run_inference(session, ctx, as_of=day, store=artifact_store())
        if result is None:
            logger.info("Intelligence désactivée", extra={"company_id": company_id})
            return 0
        logger.info(
            "Prévisions et insights produits",
            extra={
                "company_id": company_id,
                "as_of": day.isoformat(),
                "forecasts": result.inferred.forecast_rows,
                "insights": result.insights.emitted,
                "notified": result.insights.notified,
            },
        )
        return result.inferred.forecast_rows

    return run_for_company(company_id, as_of, _step)


@celery_app.task(name=ML_INFER)
@tracked_job(ML_INFER)
def infer_all() -> int:
    """Éventail : une sous-tâche par entreprise."""
    count = 0
    for company_id in each_company():
        infer.delay(str(company_id))
        count += 1
    return count
