"""Application Celery (image Docker, zone B du Diagramme 2).

Phase 00 : instance nue, aucune tâche enregistrée. L'URL du broker est lue
directement dans l'environnement ; elle passera par `app.core.config` en phase 01.
"""

import os

from celery import Celery

broker_url = os.environ.get("COGES_REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("coges", broker=broker_url, backend=broker_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
)
