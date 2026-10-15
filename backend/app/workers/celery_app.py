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

import inspect
import logging
from typing import Any

from celery import Celery, Task
from celery.signals import (
    beat_embedded_init,
    beat_init,
    worker_init,
    worker_process_init,
    worker_ready,
)

from app.core.config import get_settings
from app.core.heartbeat import Heartbeat
from app.core.logging import configure_logging
from app.core.observability import init_sentry, tag_job
from app.workers import beat as _beat

configure_logging()

logger = logging.getLogger(__name__)
settings = get_settings()


class CogesTask(Task):  # type: ignore[misc]
    """Tâche qui se nomme et nomme son entreprise auprès de Sentry (ADR 0077).

    L'intégration Celery de Sentry ouvre une portée par tâche autour de `__call__` :
    les étiquettes posées ici ne valent que pour cette exécution.
    """

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        from app.workers.jobs import company_id_of  # noqa: PLC0415

        try:
            tag_job(self.name, company_id_of(inspect.signature(self.run), args, kwargs))
        except Exception:  # pragma: no cover - une étiquette ne fait jamais échouer une tâche
            logger.debug("Étiquettes Sentry non posées", exc_info=True)
        return super().__call__(*args, **kwargs)


celery_app = Celery(
    "coges",
    broker=settings.redis_url,
    backend=settings.redis_url,
    task_cls=CogesTask,
    include=[
        "app.workers.tasks.analytics",
        "app.workers.tasks.notifications",
        "app.workers.tasks.audit",
        "app.workers.tasks.reconcile",
        "app.workers.tasks.ml_features",
        "app.workers.tasks.ml_train",
        "app.workers.tasks.ml_infer",
        "app.workers.tasks.exports",
        "app.workers.tasks.system",
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
    task_time_limit=_beat.TASK_TIME_LIMIT_SECONDS,
)

# Le planificateur lit `celery_app.conf.beat_schedule`.
celery_app.conf.beat_schedule = _beat.BEAT_SCHEDULE


#: Battements de ce processus, gardés pour que le fil ne soit pas ramassé.
_heartbeats: dict[str, Heartbeat] = {}


def _start_heartbeat(component: str) -> None:
    if component not in _heartbeats:
        _heartbeats[component] = Heartbeat(component).start()


@worker_init.connect
def _prepare_worker(**_: Any) -> None:
    """Processus principal du worker, avant la première tâche (ADR 0077).

    Sentry est initialisé ici et non à l'import : le relais importe ce module pour
    publier, et doit rester étiqueté `relay`. Un `SystemExit` et non une exception :
    Celery avale les exceptions levées par un récepteur de signal, il ne laisse
    passer que celle-ci.
    """
    from app.core.heartbeat import redis_client  # noqa: PLC0415
    from app.workers.preflight import (  # noqa: PLC0415
        RedisEvictionPolicyError,
        check_redis_eviction_policy,
    )

    init_sentry("worker", celery=True)
    try:
        check_redis_eviction_policy(redis_client(), settings.env)
    except RedisEvictionPolicyError:
        logger.critical("Démarrage du worker refusé", exc_info=True)
        raise SystemExit(1) from None


@worker_ready.connect
def _worker_heartbeat(**_: Any) -> None:
    _start_heartbeat("worker")


@beat_init.connect
def _beat_heartbeat(**_: Any) -> None:
    init_sentry("beat", celery=True)
    _start_heartbeat("beat")


@beat_embedded_init.connect
def _embedded_beat_heartbeat(**_: Any) -> None:
    """`celery worker --beat` (`make worker`) : beat vit dans le worker, il bat aussi."""
    _start_heartbeat("beat")


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
