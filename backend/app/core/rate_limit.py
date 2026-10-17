"""Limitation de débit (décision 16, ADR 0042) et freinage de la connexion (ADR 0078).

Fenêtre fixe d'une minute, compteur Redis `INCR` + `EXPIRE` :

* ``rl:ip:{ip}:{minute}``        — toute requête, posé par le middleware ;
* ``rl:login:{ip}:{minute}``     — `POST /auth/login`, plafond bien plus bas ;
* ``rl:tenant:{company}:{minute}`` — toute requête authentifiée, posé par
  `get_tenant_session` **après** la relecture de l'utilisateur : le `company_id`
  vient du serveur, jamais du client.

Freinage **par compte** (ADR 0078), clé ``rl:acct:{sha256(slug|identifiant)}`` : aucun
identifiant en clair dans Redis, et la clé est posée pour ce qui a été **tapé**, que le
compte existe ou non. Au-delà de `login_throttle_free_failures` échecs dans la fenêtre,
chaque échec impose une attente (1, 2, 4… minutes, `login_throttle_max_wait_minutes` au
plus). On freine, on ne verrouille jamais : un verrou permettrait à n'importe qui de
bloquer la gérante.

Une panne de Redis **désactive** la limite au lieu de faire échouer la requête : la
limitation protège la disponibilité, elle ne doit pas devenir la cause d'une panne
(même règle que le cache, `app.core.cache`). Seule exception, la **connexion** : son
plafond par IP et son freinage par compte passent sur un compteur en mémoire du
processus (`_MemoryCounters`). Sur Vercel, chaque instance a sa propre mémoire : c'est
un frein dégradé, pas une garantie.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sentry_sdk

from app.core import cache
from app.core.config import get_settings
from app.core.errors import RateLimitedError

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60

#: Horloge substituable par les tests, pour qu'une fenêtre ne bascule pas en plein cas.
_clock = time.time

#: Un échec du compte : incrémente, pose l'attente au-delà du seuil, prolonge la clé.
#: Atomique côté Redis : deux échecs simultanés ne peuvent pas lire le même compte.
_ACCOUNT_FAILURE_LUA = """
local fails = redis.call('HINCRBY', KEYS[1], 'fails', 1)
local now = tonumber(ARGV[1])
local free = tonumber(ARGV[2])
local window = tonumber(ARGV[3])
local max_wait = tonumber(ARGV[4])
local until_at = 0
if fails >= free then
  local wait = math.min(max_wait, 60 * 2 ^ (fails - free))
  until_at = now + wait
  redis.call('HSET', KEYS[1], 'until', until_at)
  local ttl = redis.call('TTL', KEYS[1])
  if ttl < wait + window then
    redis.call('EXPIRE', KEYS[1], math.ceil(wait + window))
  end
elseif fails == 1 then
  redis.call('EXPIRE', KEYS[1], window)
end
return {fails, tostring(until_at)}
"""


class _MemoryCounters:
    """Compteurs de secours, en mémoire du processus, bornés et protégés par un verrou.

    Au-delà de `capacity` clés, les plus anciennement touchées sont évincées : un
    attaquant qui varie les identifiants ne fait pas grossir la mémoire sans fin.
    """

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple[dict[str, float], float]] = OrderedDict()

    def _entry(self, key: str, now: float) -> dict[str, float] | None:
        found = self._data.get(key)
        if found is None:
            return None
        values, expires_at = found
        if expires_at <= now:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return values

    def _store(self, key: str, values: dict[str, float], expires_at: float) -> None:
        self._data[key] = (values, expires_at)
        self._data.move_to_end(key)
        while len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def incr(self, key: str, ttl: float, now: float) -> int:
        with self._lock:
            values = self._entry(key, now)
            if values is None:
                self._store(key, {"count": 1}, now + ttl)
                return 1
            values["count"] += 1
            return int(values["count"])

    def account_until(self, key: str, now: float) -> float:
        with self._lock:
            values = self._entry(key, now)
            return values.get("until", 0.0) if values else 0.0

    def account_failure(
        self, key: str, now: float, *, free: int, window: float, max_wait: float
    ) -> tuple[int, float]:
        with self._lock:
            found = self._data.get(key)
            values = self._entry(key, now)
            expires_at = found[1] if values is not None and found is not None else now + window
            if values is None:
                values = {"fails": 0}
            values["fails"] += 1
            fails = int(values["fails"])
            until_at = 0.0
            if fails >= free:
                wait = min(max_wait, 60 * 2 ** (fails - free))
                until_at = now + wait
                values["until"] = until_at
                expires_at = max(expires_at, now + wait + window)
            self._store(key, values, expires_at)
            return fails, until_at

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def __len__(self) -> int:
        return len(self._data)


_memory = _MemoryCounters(get_settings().login_throttle_memory_keys)
_degraded_reported_at = 0.0
_degraded_lock = threading.Lock()


def _report_degraded() -> None:
    """Journal et Sentry, une fois par minute au plus : la panne doit se voir sans noyer."""
    global _degraded_reported_at
    now = _clock()
    with _degraded_lock:
        if now - _degraded_reported_at < WINDOW_SECONDS:
            return
        _degraded_reported_at = now
    logger.warning("Limitation de connexion en mode dégradé (Redis indisponible)", exc_info=True)
    sentry_sdk.capture_message("limitation de connexion en mode dégradé", level="warning")


def _redis() -> Any | None:
    return cache.get_client()


def _hit(bucket: str, limit: int, *, degraded_in_memory: bool = False) -> None:
    """Incrémente le compteur de la fenêtre courante ; lève 429 au-delà de `limit`."""
    if limit <= 0:
        return
    now = int(_clock())
    window = now // WINDOW_SECONDS
    counter_key = f"{cache.NAMESPACE}:rl:{bucket}:{window}"
    count: int | None = None
    client = _redis()
    if client is not None:
        try:
            pipeline = client.pipeline()
            pipeline.incr(counter_key)
            pipeline.expire(counter_key, WINDOW_SECONDS * 2)
            count = int(pipeline.execute()[0])
        except Exception:
            if not degraded_in_memory:
                logger.warning("Limitation de débit indisponible (Redis)", exc_info=True)
    if count is None:
        if not degraded_in_memory:
            return
        _report_degraded()
        count = _memory.incr(counter_key, WINDOW_SECONDS * 2, now)
    if count > limit:
        retry_after = WINDOW_SECONDS - (now % WINDOW_SECONDS)
        raise RateLimitedError(retry_after, scope=bucket.split(":", 1)[0])


def hit_ip(ip: str) -> None:
    _hit(f"ip:{ip}", get_settings().rate_limit_ip_per_minute)


def hit_login(ip: str) -> None:
    _hit(f"login:{ip}", get_settings().rate_limit_login_per_minute, degraded_in_memory=True)


def hit_tenant(company_id: UUID) -> None:
    _hit(f"tenant:{company_id}", get_settings().rate_limit_tenant_per_minute)


# ------------------------------------------------------------- freinage par compte


@dataclass(frozen=True, slots=True)
class AccountFailure:
    """Effet d'un échec sur le compteur du compte tapé."""

    failures: int
    #: Instant (epoch) jusqu'auquel la connexion est freinée ; 0 : aucune attente.
    wait_until: float


def account_key(company_slug: str, identifier: str) -> str:
    """Clé du compteur : un condensat, jamais l'identifiant en clair."""
    digest = hashlib.sha256(f"{company_slug.lower()}|{identifier}".encode()).hexdigest()
    return f"{cache.NAMESPACE}:rl:acct:{digest}"


def _wait_error(wait_until: float, now: float) -> RateLimitedError:
    remaining = max(1, math.ceil(wait_until - now))
    minutes = math.ceil(remaining / 60)
    unit = "minute" if minutes == 1 else "minutes"
    error = RateLimitedError(remaining, scope="account")
    error.message = f"Trop d'essais. Réessayez dans {minutes} {unit}."
    return error


def check_account(company_slug: str, identifier: str) -> None:
    """Lève 429 si le compte tapé est en attente. À appeler **avant** toute vérification.

    Même réponse que le compte existe ou non, et aucun hachage Argon2 offert à
    l'attaquant pendant l'attente.
    """
    key = account_key(company_slug, identifier)
    now = _clock()
    wait_until: float | None = None
    client = _redis()
    if client is not None:
        try:
            raw = client.hget(key, "until")
            wait_until = float(raw) if raw else 0.0
        except Exception:
            wait_until = None
    if wait_until is None:
        _report_degraded()
        wait_until = _memory.account_until(key, now)
    if wait_until > now:
        raise _wait_error(wait_until, now)


def record_account_failure(company_slug: str, identifier: str) -> AccountFailure:
    """Compte un échec ; au-delà du seuil, pose l'attente (doublée, plafonnée)."""
    settings = get_settings()
    key = account_key(company_slug, identifier)
    now = _clock()
    free = settings.login_throttle_free_failures
    window = settings.login_throttle_window_minutes * 60
    max_wait = settings.login_throttle_max_wait_minutes * 60
    client = _redis()
    if client is not None:
        try:
            fails, until_at = client.eval(
                _ACCOUNT_FAILURE_LUA, 1, key, repr(now), free, window, max_wait
            )
            return AccountFailure(failures=int(fails), wait_until=float(until_at))
        except Exception:
            pass
    _report_degraded()
    fails, until_at = _memory.account_failure(key, now, free=free, window=window, max_wait=max_wait)
    return AccountFailure(failures=fails, wait_until=until_at)


def reset_account(company_slug: str, identifier: str) -> None:
    """Remise à zéro après une connexion réussie."""
    key = account_key(company_slug, identifier)
    _memory.delete(key)
    client = _redis()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:
        _report_degraded()
