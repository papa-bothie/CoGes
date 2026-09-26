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

from typing import Any

from celery import Celery
from celery.signals import beat_init, worker_process_init

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.observability import init_sentry

configure_logging()
init_sentry("worker")

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
        "app.workers.tasks.exports",
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


@worker_process_init.connect
def _refuse_forbidden_role(**_: Any) -> None:
    """Garde-fou 1 de l'ADR 0042 : aucun worker ne tourne sous `coges_owner`.

    Vérifié à l'initialisation de chaque processus enfant, avant la première tâche :
    un DSN propriétaire glissé dans l'environnement arrête le worker au lieu de lui
    ouvrir, par un changement de rôle, le `BYPASSRLS` de `coges_auth`.
    """
    from app.core.database import get_analytics_session_factory, get_engine  # noqa: PLC0415
    from app.core.role_guard import assert_runtime_role  # noqa: PLC0415

    assert_runtime_role(get_engine())
    if settings.database_url_analytics:
        engine = get_analytics_session_factory().kw["bind"]
        assert_runtime_role(engine)


@beat_init.connect
def _refuse_forbidden_role_in_beat(**_: Any) -> None:
    """Même garde-fou pour le planificateur, qui porte le DSN applicatif."""
    from app.core.database import get_engine  # noqa: PLC0415
    from app.core.role_guard import assert_runtime_role  # noqa: PLC0415

    assert_runtime_role(get_engine())
