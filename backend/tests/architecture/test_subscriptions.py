"""Aucun événement ne se perd entre l'outbox et les tâches.

`app/workers/subscriptions.py` est le seul endroit où un type d'événement est relié
à une tâche. Le lien y est déclaré par **nom**, pour éviter un cycle d'import entre
le bus, l'application Celery et les tâches — mais un nom ne se vérifie pas tout seul.
C'est ce que font ces tests : un type sans abonné serait écrit, publié, puis perdu ;
un abonné dont le nom ne correspond à aucune tâche enregistrée ferait échouer la
publication à chaud, en production, sur le premier événement de ce type.

La forme de panne la plus difficile à voir est la première : rien n'échoue, le
tableau de bord se contente de ne jamais bouger.
"""

from __future__ import annotations

from app.core.events.types import EventType
from app.workers import subscriptions
from app.workers.beat import BEAT_SCHEDULE, BEAT_TICK, JOB_FRESHNESS
from app.workers.celery_app import celery_app

# Importés pour leur effet de bord : l'enregistrement des tâches auprès de Celery.
import app.workers.tasks.analytics  # noqa: F401  isort:skip
import app.workers.tasks.audit  # noqa: F401  isort:skip
import app.workers.tasks.notifications  # noqa: F401  isort:skip
import app.workers.tasks.exports  # noqa: F401  isort:skip
import app.workers.tasks.reconcile  # noqa: F401  isort:skip
import app.workers.tasks.ml_features  # noqa: F401  isort:skip
import app.workers.tasks.ml_train  # noqa: F401  isort:skip
import app.workers.tasks.ml_infer  # noqa: F401  isort:skip
import app.workers.tasks.system  # noqa: F401  isort:skip


def test_every_event_type_has_at_least_one_subscriber() -> None:
    """Les dix types de la notation fermée sont tous écoutés."""
    unheard = [kind.value for kind in EventType if not subscriptions.SUBSCRIPTIONS.get(kind)]
    assert unheard == [], f"Types d'événement sans abonné : {unheard}"


def test_the_subscription_table_invents_no_event_type() -> None:
    """Et réciproquement : aucun abonnement ne vise un type qui n'existe pas.

    La liste des dix notations est fermée (`CLAUDE.md` § 4) ; un abonnement à un
    onzième type serait le premier symptôme d'une notation ajoutée en douce.
    """
    assert set(subscriptions.SUBSCRIPTIONS) == set(EventType)


def test_every_subscribed_name_is_a_registered_task() -> None:
    """Chaque nom déclaré correspond à une tâche réellement enregistrée."""
    declared = {name for names in subscriptions.SUBSCRIPTIONS.values() for name in names}
    missing = sorted(name for name in declared if name not in celery_app.tasks)
    assert missing == [], f"Abonnements fantômes : {missing}"


def test_every_included_task_module_is_imported_here() -> None:
    """Un module de tâches ajouté à `include` doit l'être ici, sinon le test d'après
    conclurait « tâche introuvable » pour une tâche qui existe bel et bien."""
    import sys

    included = set(celery_app.conf.include)
    assert included <= set(sys.modules), sorted(included - set(sys.modules))


def test_every_scheduled_name_is_a_registered_task() -> None:
    """Même exigence pour le planificateur : un batch fantôme ne se plaint jamais."""
    scheduled = {entry["task"] for entry in BEAT_SCHEDULE.values()}
    missing = sorted(name for name in scheduled if name not in celery_app.tasks)
    assert missing == [], f"Tâches planifiées introuvables : {missing}"


def test_every_scheduled_task_has_a_freshness_window() -> None:
    """Toute tâche planifiée a un délai de fraîcheur, lu par `/system/workers` (ADR 0077).

    Sans lui, une tâche ajoutée à `BEAT_SCHEDULE` pourrait cesser de tourner sans que
    personne le sache. `beat_tick` est suivi dans Redis, pas dans `job_runs`.
    """
    scheduled = {entry["task"] for entry in BEAT_SCHEDULE.values()} - {BEAT_TICK}
    assert scheduled == set(JOB_FRESHNESS), sorted(scheduled ^ set(JOB_FRESHNESS))


def test_every_per_company_subtask_is_a_registered_task() -> None:
    """Les sous-tâches nommées dans `JOB_FRESHNESS` existent sous ce nom."""
    subtasks = {f.per_company for f in JOB_FRESHNESS.values() if f.per_company}
    missing = sorted(name for name in subtasks if name not in celery_app.tasks)
    assert missing == [], f"Sous-tâches introuvables : {missing}"
