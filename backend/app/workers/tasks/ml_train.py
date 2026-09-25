"""Étape 05 du Diagramme 7 : modèles versionnés, chaque semaine et par entreprise."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.intelligence.pipelines import run_training
from app.workers.beat import ML_TRAIN
from app.workers.celery_app import celery_app
from app.workers.tasks.intelligence_common import artifact_store, run_for_company
from app.workers.tenants import each_company

logger = logging.getLogger(__name__)


@celery_app.task(name="ml_train.train")
def train(company_id: str, as_of: str | None = None) -> str | None:
    """Entraîne et enregistre l'artefact de la semaine. Renvoie sa version."""

    def _step(session: Session, ctx: TenantContext, day: date) -> str | None:
        run = run_training(session, ctx, as_of=day, store=artifact_store())
        if run is None:
            return None
        logger.info(
            "Modèle entraîné",
            extra={
                "company_id": company_id,
                "model": run.model_name,
                "version": run.model_version,
                "fitted": run.fitted,
                "path": str(run.path),
            },
        )
        return run.model_version

    return run_for_company(company_id, as_of, _step)


@celery_app.task(name=ML_TRAIN)
def train_all() -> int:
    """Éventail : une sous-tâche par entreprise."""
    count = 0
    for company_id in each_company():
        train.delay(str(company_id))
        count += 1
    return count
