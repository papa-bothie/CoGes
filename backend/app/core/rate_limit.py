"""Limitation de débit par IP et par entreprise (décision 16, ADR 0042).

Fenêtre fixe d'une minute, compteur Redis `INCR` + `EXPIRE` :

* ``rl:ip:{ip}:{minute}``        — toute requête, posé par le middleware ;
* ``rl:login:{ip}:{minute}``     — `POST /auth/login`, plafond bien plus bas ;
* ``rl:tenant:{company}:{minute}`` — toute requête authentifiée, posé par
  `get_tenant_session` **après** la relecture de l'utilisateur : le `company_id`
  vient du serveur, jamais du client.

Une panne de Redis **désactive** la limite au lieu de faire échouer la requête : la
limitation protège la disponibilité, elle ne doit pas devenir la cause d'une panne
(même règle que le cache, `app.core.cache`). L'incident est journalisé.
"""

from __future__ import annotations

import logging
import time
from uuid import UUID

from app.core import cache
from app.core.config import get_settings
from app.core.errors import RateLimitedError

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60

#: Horloge substituable par les tests, pour qu'une fenêtre ne bascule pas en plein cas.
_clock = time.time


def _hit(bucket: str, limit: int) -> None:
    """Incrémente le compteur de la fenêtre courante ; lève 429 au-delà de `limit`."""
    if limit <= 0:
        return
    client = cache.get_client()
    if client is None:
        return
    now = int(_clock())
    window = now // WINDOW_SECONDS
    counter_key = f"{cache.NAMESPACE}:rl:{bucket}:{window}"
    try:
        pipeline = client.pipeline()
        pipeline.incr(counter_key)
        pipeline.expire(counter_key, WINDOW_SECONDS * 2)
        count = int(pipeline.execute()[0])
    except Exception:
        logger.warning("Limitation de débit indisponible (Redis)", exc_info=True)
        return
    if count > limit:
        retry_after = WINDOW_SECONDS - (now % WINDOW_SECONDS)
        raise RateLimitedError(retry_after, scope=bucket.split(":", 1)[0])


def hit_ip(ip: str) -> None:
    _hit(f"ip:{ip}", get_settings().rate_limit_ip_per_minute)


def hit_login(ip: str) -> None:
    _hit(f"login:{ip}", get_settings().rate_limit_login_per_minute)


def hit_tenant(company_id: UUID) -> None:
    _hit(f"tenant:{company_id}", get_settings().rate_limit_tenant_per_minute)
