"""Sonde de disponibilité complète : l'API, PostgreSQL et Redis (ADR 0081).

`GET /api/v1/health` dit seulement que le processus répond. `GET /api/v1/health/ready`
vérifie aussi ce dont une requête métier a besoin, pour la sonde externe :

* **PostgreSQL** : `SELECT 1` par le rôle `coges_app`, sans contexte d'entreprise ni
  lecture de table, borné à 2 s ;
* **Redis** : `PING` sur un client neuf (`heartbeat.redis_client`, borné à 2 s). Le
  client mémorisé de `app.core.cache` garde un `None` après un premier échec : il ne
  peut pas servir de sonde. Sans `COGES_REDIS_URL` posée, Redis est `not_configured` et
  ne fait pas échouer la sonde (l'adresse par défaut n'est qu'une commodité locale).

La réponse ne dit que l'état de chaque dépendance : aucun message d'erreur, aucun hôte.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import text

from app.core import heartbeat
from app.core.config import get_settings
from app.core.database import get_session_factory

logger = logging.getLogger(__name__)

CheckState = Literal["ok", "down", "not_configured"]


class ReadinessChecks(BaseModel):
    database: CheckState
    redis: CheckState


class ReadinessRead(BaseModel):
    """Corps de `/health/ready`, le même en 200 et en 503."""

    status: Literal["ok", "unavailable"]
    checks: ReadinessChecks


def check_database() -> CheckState:
    try:
        with get_session_factory()() as session, session.begin():
            session.execute(text("SET LOCAL statement_timeout = '2s'"))
            session.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Sonde de disponibilité : PostgreSQL injoignable", exc_info=True)
        return "down"
    return "ok"


def redis_configured() -> bool:
    """Vrai si l'adresse de Redis a été donnée par l'environnement, pas par défaut."""
    return "redis_url" in get_settings().model_fields_set


def check_redis() -> CheckState:
    if not redis_configured():
        return "not_configured"
    try:
        client = heartbeat.redis_client()
        try:
            client.ping()
        finally:
            client.close()
    except Exception:
        logger.warning("Sonde de disponibilité : Redis injoignable", exc_info=True)
        return "down"
    return "ok"


def readiness() -> ReadinessRead:
    """Interroge chaque dépendance ; `unavailable` dès que l'une est `down`."""
    checks = ReadinessChecks(database=check_database(), redis=check_redis())
    down = "down" in (checks.database, checks.redis)
    return ReadinessRead(status="unavailable" if down else "ok", checks=checks)
