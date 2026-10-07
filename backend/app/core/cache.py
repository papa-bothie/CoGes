"""Cache court par tenant, sur Redis.

La décision 14 de l'architecture demande « un cache court par tenant, invalidé par
événement » pour les indicateurs d'accueil. Deux règles en découlent, et elles ne se
négocient pas :

1. **La clé porte le `company_id`.** Une clé partagée entre entreprises serait une
   quatrième barrière à franchir pour une fuite, après les trois de la base — sauf
   qu'ici aucune RLS ne veille. Le préfixe est construit ici, jamais par l'appelant.
2. **Toute panne est avalée.** Redis est déclaré non critique par l'architecture
   (décision 04 : l'audit et l'outbox n'en dépendent pas). Un cache indisponible fait
   donc recalculer et servir, jamais échouer : le tableau de bord d'un gérant ne
   tombe pas parce qu'un cache a redémarré.

Le cache ne contient **jamais** une donnée qui n'existe pas déjà en base : il ne peut
pas devenir une source de vérité, seulement une source de lenteur évitée.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, cast
from uuid import UUID

import redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tenancy import on_commit

logger = logging.getLogger(__name__)

#: Clé du tableau de bord. Ici et non dans `modules/dashboard` : les modules qui
#: écrivent (ventes, finance, dépenses) la vident après COMMIT et ne peuvent pas
#: importer un module de restitution, qui est au-dessus d'eux (ADR 0061).
DASHBOARD_KEY = "dashboard"

#: Préfixe commun, pour qu'un `FLUSHDB` ciblé ou un audit de clés reste possible.
NAMESPACE = "coges"


@lru_cache
def get_client() -> redis.Redis | None:
    """Client Redis du processus, ou `None` si la connexion est impossible.

    Le `None` est un état normal, pas une erreur : il signifie « pas de cache », et
    tous les appels ci-dessous savent s'en passer.
    """
    try:
        client = redis.Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
    except Exception:  # pragma: no cover - dépend d'un service externe
        logger.warning(
            "Redis injoignable : le cache est désactivé pour ce processus", exc_info=True
        )
        return None
    return client


def key(company_id: UUID, name: str) -> str:
    """Clé d'un tenant. Le `company_id` est toujours devant, jamais optionnel."""
    return f"{NAMESPACE}:{company_id}:{name}"


def get_json(company_id: UUID, name: str) -> Any | None:
    """Valeur mise en cache, ou `None` s'il n'y en a pas — ou si Redis est absent."""
    client = get_client()
    if client is None:
        return None
    try:
        # redis-py déclare un type unique pour ses clients synchrone et asynchrone :
        # le `cast` dit ce que la variante synchrone rend réellement.
        raw = cast(str | None, client.get(key(company_id, name)))
    except Exception:  # pragma: no cover - dépend d'un service externe
        logger.warning("Lecture du cache échouée ; recalcul", exc_info=True)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Une valeur illisible est une valeur absente : on ne sert jamais un
        # fragment, et la clé se réécrira au prochain calcul.
        logger.warning("Valeur de cache illisible ; ignorée", extra={"cache_key": name})
        return None


def set_json(company_id: UUID, name: str, value: Any, *, ttl_seconds: int) -> None:
    """Met en cache pour `ttl_seconds`. Un TTL nul ou négatif n'écrit rien."""
    client = get_client()
    if client is None or ttl_seconds <= 0:
        return
    try:
        client.setex(key(company_id, name), ttl_seconds, json.dumps(value, default=str))
    except Exception:  # pragma: no cover - dépend d'un service externe
        logger.warning("Écriture du cache échouée ; ignorée", exc_info=True)


def invalidate(company_id: UUID, *names: str) -> None:
    """Oublie ces clés pour ce tenant.

    Appelé par les consommateurs après reconstruction des agrégats : c'est
    l'« invalidation par événement » de la décision 14. Un échec est sans gravité,
    le TTL court rattrape.
    """
    client = get_client()
    if client is None or not names:
        return
    try:
        client.delete(*(key(company_id, name) for name in names))
    except Exception:  # pragma: no cover - dépend d'un service externe
        logger.warning("Invalidation du cache échouée ; le TTL rattrapera", exc_info=True)


def invalidate_after_commit(session: Session, company_id: UUID, *names: str) -> None:
    """Vide les clés `names` de l'entreprise une fois la transaction validée.

    L'invalidation par le worker reste le filet ; celle-ci rend l'écriture visible
    dès la lecture suivante, sans attendre ni le relais ni le TTL (ADR 0061).
    """
    on_commit(session, lambda: invalidate(company_id, *names))
