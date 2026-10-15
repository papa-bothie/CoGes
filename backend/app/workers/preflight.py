"""Contrôles de démarrage du worker (ADR 0077).

Redis porte la file Celery. Sous une politique d'éviction autre que `noeviction`,
Redis plein **supprime des clés** pour faire de la place — des tâches en attente
disparaîtraient sans erreur ni trace. `noeviction` fait au contraire échouer
l'écriture, ce qui se voit.

La politique se lit par `INFO memory`, que Redis Cloud autorise, et non par
`CONFIG GET`, souvent refusé par les hébergeurs.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import redis

logger = logging.getLogger(__name__)

REQUIRED_POLICY = "noeviction"


class RedisEvictionPolicyError(RuntimeError):
    """Redis peut évincer des clés : la file Celery n'est pas sûre."""


def check_redis_eviction_policy(client: redis.Redis, env: str) -> str | None:
    """Vérifie la politique d'éviction ; lève en production, avertit ailleurs.

    Rend la politique lue, ou `None` si Redis n'a pas répondu (le worker ne pourra
    de toute façon pas consommer, et le dira lui-même).
    """
    try:
        info = cast(dict[str, Any], client.info("memory"))
    except Exception:
        logger.warning("Politique d'éviction de Redis illisible", exc_info=True)
        return None
    policy = str(info.get("maxmemory_policy", ""))
    if policy == REQUIRED_POLICY:
        return policy
    message = (
        f"Redis est en maxmemory-policy {policy or 'inconnue'} : des tâches en attente "
        f"peuvent être évincées. Réglez {REQUIRED_POLICY} (docs/runbooks/workers.md)."
    )
    if env == "production":
        raise RedisEvictionPolicyError(message)
    logger.warning(message)
    return policy
