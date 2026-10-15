"""Battements de cœur des processus de la zone B (ADR 0077).

Le worker, beat et le relais écrivent chacun, toutes les 30 s, une clé Redis
`coges:heartbeat:<composant>:<hôte>` dont la valeur est l'heure Unix de l'écriture.
La clé expire seule au bout de 120 s : un processus mort disparaît du bilan sans
qu'aucun ménage soit nécessaire.

Deux lecteurs :

* `python -m app.workers.health` dans le conteneur (healthcheck Docker) ;
* `GET /api/v1/system/workers`, qui agrège les trois composants.

Les battements passent par Redis et non par la base : la base de préproduction peut
s'endormir entre deux passages du relais (ADR 0040), un battement en base l'en
empêcherait.

`beat_tick` suit la même voie : la tâche `system.beat_tick`, planifiée toutes les
5 min, laisse ici l'heure de son dernier passage. C'est la preuve que beat planifie
**et** qu'un worker consomme.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import cast

import redis

from app.core.cache import NAMESPACE
from app.core.config import get_settings

logger = logging.getLogger(__name__)

COMPONENTS = ("worker", "beat", "relay")
INTERVAL_SECONDS = 30
TTL_SECONDS = 120
#: Au-delà, le battement est jugé absent, même si la clé n'a pas encore expiré.
FRESH_SECONDS = 90

PREFIX = f"{NAMESPACE}:heartbeat"
#: Dernier passage de `system.beat_tick`.
BEAT_TICK_KEY = f"{NAMESPACE}:ops:beat_tick"
#: Une clé à part, gardée deux jours : son absence dit « jamais », pas « expiré ».
BEAT_TICK_TTL_SECONDS = 2 * 24 * 3600


def redis_client() -> redis.Redis:
    """Client Redis neuf, sans cache : la surveillance doit voir une panne de Redis.

    `app.core.cache.get_client` mémorise un `None` au premier échec et ne réessaie
    jamais ; un battement qui ferait de même resterait muet après un redémarrage de
    Redis.
    """
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def hostname() -> str:
    """Nom de l'hôte : l'identifiant du conteneur sous Docker."""
    return socket.gethostname()


def heartbeat_key(component: str, host: str) -> str:
    return f"{PREFIX}:{component}:{host}"


def beat(client: redis.Redis, component: str, host: str, *, now: float | None = None) -> None:
    """Écrit un battement. Lève si Redis est injoignable : à l'appelant de décider."""
    stamp = time.time() if now is None else now
    client.set(heartbeat_key(component, host), f"{stamp:.3f}", ex=TTL_SECONDS)


def age_seconds(
    client: redis.Redis, component: str, host: str, *, now: float | None = None
) -> float | None:
    """Âge du dernier battement de ce composant sur cet hôte, ou `None` s'il n'y en a pas."""
    raw = cast(str | None, client.get(heartbeat_key(component, host)))
    if raw is None:
        return None
    current = time.time() if now is None else now
    return max(0.0, current - float(raw))


@dataclass(frozen=True, slots=True)
class Pulse:
    """Un battement lu : quel composant, sur quel hôte, il y a combien de secondes."""

    component: str
    host: str
    age_seconds: float

    @property
    def fresh(self) -> bool:
        return self.age_seconds < FRESH_SECONDS


def read_pulses(client: redis.Redis, *, now: float | None = None) -> list[Pulse]:
    """Tous les battements présents, tous composants et tous hôtes confondus."""
    current = time.time() if now is None else now
    pulses: list[Pulse] = []
    for raw_key in client.scan_iter(match=f"{PREFIX}:*", count=100):
        key = cast(str, raw_key)
        component, _, host = key.removeprefix(f"{PREFIX}:").partition(":")
        raw = cast(str | None, client.get(key))
        if raw is None or component not in COMPONENTS:
            continue
        pulses.append(Pulse(component, host, max(0.0, current - float(raw))))
    return sorted(pulses, key=lambda pulse: (pulse.component, pulse.host))


def record_beat_tick(client: redis.Redis, *, now: float | None = None) -> None:
    stamp = time.time() if now is None else now
    client.set(BEAT_TICK_KEY, f"{stamp:.3f}", ex=BEAT_TICK_TTL_SECONDS)


def beat_tick_age(client: redis.Redis, *, now: float | None = None) -> float | None:
    raw = cast(str | None, client.get(BEAT_TICK_KEY))
    if raw is None:
        return None
    current = time.time() if now is None else now
    return max(0.0, current - float(raw))


class Heartbeat:
    """Fil démon qui bat toutes les 30 s tant que le processus vit.

    Une panne de Redis est journalisée, jamais propagée : le processus continue son
    travail, et c'est justement l'absence de battement qui donnera l'alerte.
    """

    def __init__(
        self,
        component: str,
        *,
        client: redis.Redis | None = None,
        host: str | None = None,
        interval: float = INTERVAL_SECONDS,
    ) -> None:
        if component not in COMPONENTS:
            raise ValueError(f"composant inconnu : {component}")
        self.component = component
        self._client = client
        self._host = host or hostname()
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def beat_once(self) -> bool:
        try:
            if self._client is None:
                self._client = redis_client()
            beat(self._client, self.component, self._host)
        except Exception:
            logger.warning(
                "Battement de cœur impossible", extra={"component": self.component}, exc_info=True
            )
            return False
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self.beat_once()
            self._stop.wait(self._interval)

    def start(self) -> Heartbeat:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name=f"heartbeat-{self.component}", daemon=True
            )
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
