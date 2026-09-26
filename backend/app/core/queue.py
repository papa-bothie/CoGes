"""Enfilement d'une tâche worker depuis l'API — la flèche A→B du Diagramme 2.

« API → Redis pour l'enfilement » : l'API dépose un message, elle n'exécute rien.
La tâche est désignée **par son nom** (`send_task`) : l'API n'importe aucun module de
`app.workers`, donc ni les tâches, ni leurs dépendances (le groupe `ml`, entre autres).

Réservé aux demandes explicites d'un utilisateur (un export). Un fait métier, lui,
passe par l'outbox (`business_events`) et le relais, jamais par ici : seul l'outbox
garantit « écrit avec la donnée, publié après COMMIT » (décision 04).

Une panne de Redis n'annule pas la demande : elle reste `pending` en base, et le
balayage nocturne des exports la renfile (ADR 0041).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from celery import Celery

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Délai avant exécution : laisse à la transaction de la requête le temps de
#: commiter. Le worker, lui, réessaie s'il ne trouve pas encore la ligne.
DEFAULT_COUNTDOWN_SECONDS = 2


@lru_cache
def _producer() -> Celery:
    settings = get_settings()
    producer = Celery("coges-api", broker=settings.redis_url)
    # Une requête HTTP n'attend pas Redis : un seul essai, court.
    producer.conf.update(task_publish_retry=False, broker_connection_timeout=2)
    return producer


def enqueue(task_name: str, *, countdown: int = DEFAULT_COUNTDOWN_SECONDS, **kwargs: Any) -> bool:
    """Dépose la tâche ; renvoie `False` (et journalise) si Redis est injoignable."""
    try:
        _producer().send_task(task_name, kwargs=kwargs, countdown=countdown)
    except Exception:
        logger.warning("Enfilement impossible", extra={"task": task_name}, exc_info=True)
        return False
    return True
