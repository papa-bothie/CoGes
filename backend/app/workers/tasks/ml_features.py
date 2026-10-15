"""Étapes 02 à 04 du Diagramme 7 : features figées de la veille, chaque nuit."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.intelligence.pipelines import run_features
from app.workers.beat import ML_FEATURES
from app.workers.celery_app import celery_app
from app.workers.jobs import tracked_job
from app.workers.tasks.intelligence_common import run_for_company
from app.workers.tenants import each_company

logger = logging.getLogger(__name__)


@celery_app.task(name="ml_features.compute")
@tracked_job("ml_features.compute", ping_as=ML_FEATURES)
def compute(company_id: str, as_of: str | None = None) -> int:
    """Photographie les produits d'une entreprise. Renvoie le nombre de lignes neuves."""

    def _step(session: Session, ctx: TenantContext, day: date) -> int:
        run = run_features(session, ctx, as_of=day)
        if run is None:
            logger.info("Intelligence désactivée", extra={"company_id": company_id})
            return 0
        logger.info(
            "Features figées",
            extra={
                "company_id": company_id,
                "as_of": day.isoformat(),
                "written": run.written,
                "labelled": run.labelled,
            },
        )
        return run.written

    return run_for_company(company_id, as_of, _step)


@celery_app.task(name=ML_FEATURES)
@tracked_job(ML_FEATURES)
def compute_all() -> int:
    """Éventail : une sous-tâche par entreprise."""
    count = 0
    for company_id in each_company():
        compute.delay(str(company_id))
        count += 1
    return count
