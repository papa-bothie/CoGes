"""Transport Redis du bus d'événements, via Celery.

Implémente le `EventBus` que `app/core/events/bus.py` décrit depuis la phase 02. Le
choix du transport vit ici, dans l'image worker : le noyau n'importe pas Celery, donc
remplacer Redis ne toucherait aucun émetteur (décision 04).

Le bus ne sait rien du métier. Il lit les abonnements dans `subscriptions.py` et
`send_task` par **nom** : il n'importe aucune tâche, donc aucun cycle d'import.
"""

from __future__ import annotations

import logging

from celery import Celery

from app.core.events.inbox import Event
from app.workers import subscriptions

logger = logging.getLogger(__name__)


class CeleryEventBus:
    """Publie un événement déjà commité vers chacun de ses abonnés."""

    def __init__(self, celery_app: Celery) -> None:
        self._celery = celery_app

    def publish(self, event: Event) -> None:
        """Enfile une tâche par abonné.

        Un type sans abonné lève `KeyError`, volontairement : ce serait un défaut de
        câblage, et publier dans le vide est la panne la plus difficile à voir. Le
        relais compte alors l'événement en échec plutôt que de le marquer publié.
        """
        message = event.as_message()
        for task_name in subscriptions.subscribers(event.event_type):
            self._celery.send_task(task_name, kwargs=message)
            logger.debug(
                "Événement publié",
                extra={
                    "event_id": event.id,
                    "task": task_name,
                    "event_type": event.event_type.value,
                },
            )
