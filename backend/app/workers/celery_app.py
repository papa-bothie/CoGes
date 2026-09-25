"""Application Celery — zone B du Diagramme 2, hors Vercel.

Même code applicatif que l'API, autre point d'entrée : les tâches appellent les
**façades de service** des modules, jamais leurs repositories ni leurs modèles.

Trois processus partagent cette instance :

* `celery worker` — exécute les tâches ;
* `celery beat`   — déclenche les tâches planifiées (`beat.py`) ;
* `python -m app.workers.relay` — le relais, qui **publie** sans rien consommer.

`task_acks_late` avec `worker_prefetch_multiplier = 1` : une tâche n'est acquittée
qu'une fois terminée, donc un worker tué la rend à la file. C'est ce qui impose des
consommateurs idempotents (`app.core.events.inbox`), et non l'inverse.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()

settings = get_settings()

celery_app = Celery(
    "coges",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks.analytics",
        "app.workers.tasks.notifications",
        "app.workers.tasks.audit",
        "app.workers.tasks.reconcile",
        "app.workers.tasks.ml_features",
        "app.workers.tasks.ml_train",
        "app.workers.tasks.ml_infer",
    ],
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    # Les corps d'événements sont du JSON depuis `business_events` : aucun pickle,
    # donc aucune désérialisation capable d'exécuter du code.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Une tâche bloquée ne doit pas immobiliser un worker indéfiniment.
    task_soft_time_limit=300,
    task_time_limit=360,
)

# Importé pour son effet de bord : le planificateur lit `celery_app.conf.beat_schedule`.
from app.workers import beat as _beat  # noqa: E402

celery_app.conf.beat_schedule = _beat.BEAT_SCHEDULE
