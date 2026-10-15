"""Tâches de surveillance (ADR 0077) : le tic de beat et la purge des traces."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text

from app.core import heartbeat
from app.core.tenancy import TenantContext, tenant_transaction
from app.workers import pings
from app.workers.beat import BEAT_TICK, PURGE_JOB_RUNS
from app.workers.celery_app import celery_app
from app.workers.jobs import tracked_job

logger = logging.getLogger(__name__)

_PURGE_JOB_RUNS = text("SELECT purge_job_runs() AS purged")


@celery_app.task(name=BEAT_TICK, ignore_result=True)
def beat_tick() -> str:
    """Preuve de vie toutes les 5 min : beat a planifié, un worker a consommé.

    Rien en base, et ce n'est pas un oubli : un passage toutes les 5 min empêcherait
    la base de préproduction de s'endormir (ADR 0040). L'heure du passage va dans
    Redis, où `/system/workers` la lit ; le ping part vers le service externe, qui
    alerte quand il ne vient plus.
    """
    try:
        heartbeat.record_beat_tick(heartbeat.redis_client())
    except Exception:
        logger.warning("Tic de beat non enregistré", exc_info=True)
    pings.ping(BEAT_TICK, ok=True)
    return "tick"


@celery_app.task(name=PURGE_JOB_RUNS)
@tracked_job(PURGE_JOB_RUNS)
def purge_job_runs() -> int:
    """Retire les traces de plus de 90 jours, par la fonction de `coges_ops`."""
    with tenant_transaction(TenantContext.bootstrap(UUID(int=0))) as session:
        purged = int(session.execute(_PURGE_JOB_RUNS).scalar_one())
    if purged:
        logger.info("Traces de tâches purgées", extra={"purged": purged})
    return purged
