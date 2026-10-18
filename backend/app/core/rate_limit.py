"""Limitation de débit (décision 16, ADR 0042) et freinage de la connexion (ADR 0078).

Fenêtre fixe d'une minute, compteur Redis `INCR` + `EXPIRE` :

* ``rl:ip:{ip}:{minute}``        — toute requête, posé par le middleware ;
* ``rl:login:{ip}:{minute}``     — `POST /auth/login`, plafond bien plus bas ;
* ``rl:tenant:{company}:{minute}`` — toute requête authentifiée, posé par
  `get_tenant_session` **après** la relecture de l'utilisateur : le `company_id`
  vient du serveur, jamais du client.

Freinage **par compte** (ADR 0078, 0088), clé ``rl:acct:{sha256(…)}`` : aucun
identifiant en clair dans Redis. La clé suit le compte quand l'identifiant tapé en
désigne un, sinon ce qui a été tapé. Au-delà de `login_throttle_free_failures` échecs
gardés `window + max_wait` (45 min), chaque échec impose une attente (1, 2, 4…
minutes, `login_throttle_max_wait_minutes` au plus). L'essai est réservé **avant**
Argon2 : une rafale parallèle ne passe pas avant le premier échec compté. On freine, on
ne verrouille jamais : un verrou permettrait à n'importe qui de bloquer la gérante.
Limite assumée : environ huit essais par 45 minutes suffisent encore à gêner une
personne en continu ; ils déclenchent l'alerte du gérant au dixième (ADR 0088).

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
from uuid import UUID, uuid4

import sentry_sdk

from app.core import cache
from app.core.config import get_settings
from app.core.errors import RateLimitedError

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60

#: Horloge substituable par les tests, pour qu'une fenêtre ne bascule pas en plein cas.
_clock = time.time


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
#
# Trois clés par compte, toutes sous le même condensat (ADR 0078, 0088) :
#   <clé>     ZSET des échecs, score = instant de l'échec ;
#   <clé>:p   ZSET des essais en cours (comptés avant Argon2, ADR 0088) ;
#   <clé>:u   instant de fin de l'attente en vigueur.
# Un échec compte pendant `window + max_wait` (45 min au barème) : assez longtemps pour
# que l'attente monte jusqu'à son plafond, assez peu pour qu'un essai isolé toutes les
# 30 min ne bloque plus la personne en continu.

#: Durée de vie d'un essai réservé dont le processus n'a jamais dit l'issue (plantage).
PENDING_SECONDS = 60

#: Réserve un essai : refus si une attente court, ou si trop d'essais sont déjà en
#: cours (une rafale parallèle passe avant le premier échec compté). Atomique.
_ACCOUNT_BEGIN_LUA = """
local now = tonumber(ARGV[1])
local member = ARGV[2]
local free = tonumber(ARGV[3])
local horizon = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - horizon)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - 60)
local until_at = tonumber(redis.call('GET', KEYS[3]) or '0')
if until_at > now then
  return {-1, tostring(until_at)}
end
local fails = redis.call('ZCARD', KEYS[1])
local pending = redis.call('ZCARD', KEYS[2])
if pending >= math.max(1, free - fails) then
  return {-1, tostring(now + 1)}
end
redis.call('ZADD', KEYS[2], now, member)
redis.call('EXPIRE', KEYS[2], 120)
return {fails, '0'}
"""

#: L'essai réservé a échoué : il devient un échec ; au-delà du seuil, l'attente
#: (1, 2, 4… minutes, `max_wait` au plus) est posée pour les essais suivants.
_ACCOUNT_FAIL_LUA = """
local now = tonumber(ARGV[1])
local member = ARGV[2]
local free = tonumber(ARGV[3])
local horizon = tonumber(ARGV[4])
local max_wait = tonumber(ARGV[5])
redis.call('ZREM', KEYS[2], member)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - horizon)
redis.call('ZADD', KEYS[1], now, member)
redis.call('EXPIRE', KEYS[1], math.ceil(horizon))
local fails = redis.call('ZCARD', KEYS[1])
local until_at = 0
if fails >= free then
  local wait = math.min(max_wait, 60 * 2 ^ (fails - free))
  until_at = now + wait
  redis.call('SET', KEYS[3], tostring(until_at), 'EX', math.ceil(wait) + 1)
end
return {fails, tostring(until_at)}
"""


@dataclass(frozen=True, slots=True)
class AccountFailure:
    """Effet d'un échec sur le compteur du compte."""

    failures: int
    #: Instant (epoch) jusqu'auquel la connexion est freinée ; 0 : aucune attente.
    wait_until: float


@dataclass(frozen=True, slots=True)
class AccountAttempt:
    """Un essai réservé, en attente de son issue (échec, succès ou ni l'un ni l'autre)."""

    key: str
    member: str
    #: Vrai pour un compte réel (clé de l'identifiant du compte, ADR 0088).
    known: bool


def account_key(company_slug: str, identifier: str) -> str:
    """Clé du compteur : un condensat, jamais l'identifiant en clair."""
    digest = hashlib.sha256(f"{company_slug.lower()}|{identifier}".encode()).hexdigest()
    return f"{cache.NAMESPACE}:rl:acct:{digest}"


def account_identity(company_slug: str, *, user_id: UUID | None, typed: str) -> tuple[str, bool]:
    """La clé suit le **compte** quand l'identifiant tapé en désigne un (ADR 0088) :
    e-mail et téléphone d'une même personne partagent alors un seul compteur. Sinon,
    elle suit ce qui a été tapé. Même forme de clé dans les deux cas : rien ne dit, de
    l'extérieur, si le compte existe."""
    if user_id is not None:
        return account_key(company_slug, f"user:{user_id}"), True
    return account_key(company_slug, typed), False


def _settings_tuple() -> tuple[int, float, float]:
    settings = get_settings()
    window = settings.login_throttle_window_minutes * 60
    max_wait = settings.login_throttle_max_wait_minutes * 60
    return settings.login_throttle_free_failures, window + max_wait, max_wait


def _wait_error(wait_until: float, now: float) -> RateLimitedError:
    remaining = max(1, math.ceil(wait_until - now))
    minutes = math.ceil(remaining / 60)
    unit = "minute" if minutes == 1 else "minutes"
    error = RateLimitedError(remaining, scope="account")
    error.message = f"Trop d'essais. Réessayez dans {minutes} {unit}."
    return error


class _MemoryAccounts:
    """Freinage par compte en mémoire du processus, quand Redis manque (ADR 0078, 0088).

    Deux réservoirs bornés et séparés : les comptes réels et les identifiants inconnus.
    Un flot d'identifiants fantaisistes n'évince donc jamais le compteur d'une victime.
    """

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._lock = threading.Lock()
        self._pools: dict[bool, OrderedDict[str, dict[str, Any]]] = {
            True: OrderedDict(),
            False: OrderedDict(),
        }

    def _entry(self, key: str, known: bool, now: float, horizon: float) -> dict[str, Any]:
        pool = self._pools[known]
        entry = pool.get(key)
        if entry is None:
            entry = {"fails": [], "pending": {}, "until": 0.0}
            pool[key] = entry
            while len(pool) > self.capacity:
                pool.popitem(last=False)
        pool.move_to_end(key)
        entry["fails"] = [at for at in entry["fails"] if at > now - horizon]
        entry["pending"] = {
            member: at for member, at in entry["pending"].items() if at > now - PENDING_SECONDS
        }
        return entry

    def begin(
        self, key: str, known: bool, member: str, now: float, *, free: int, horizon: float
    ) -> tuple[int, float]:
        with self._lock:
            entry = self._entry(key, known, now, horizon)
            if entry["until"] > now:
                return -1, float(entry["until"])
            fails = len(entry["fails"])
            if len(entry["pending"]) >= max(1, free - fails):
                return -1, now + 1
            entry["pending"][member] = now
            return fails, 0.0

    def fail(
        self,
        key: str,
        known: bool,
        member: str,
        now: float,
        *,
        free: int,
        horizon: float,
        max_wait: float,
    ) -> tuple[int, float]:
        with self._lock:
            entry = self._entry(key, known, now, horizon)
            entry["pending"].pop(member, None)
            entry["fails"].append(now)
            fails = len(entry["fails"])
            until_at = 0.0
            if fails >= free:
                until_at = now + min(max_wait, 60 * 2 ** (fails - free))
                entry["until"] = until_at
            return fails, until_at

    def cancel(self, key: str, known: bool, member: str) -> None:
        with self._lock:
            entry = self._pools[known].get(key)
            if entry is not None:
                entry["pending"].pop(member, None)

    def peek(self, key: str, known: bool) -> dict[str, Any] | None:
        with self._lock:
            entry = self._pools[known].get(key)
            return None if entry is None else {**entry, "fails": list(entry["fails"])}

    def pop(self, key: str, known: bool) -> dict[str, Any] | None:
        """Retire et rend l'état d'un compte : à reporter dans Redis revenu, ou à oublier."""
        with self._lock:
            return self._pools[known].pop(key, None)

    def __len__(self) -> int:
        return sum(len(pool) for pool in self._pools.values())


_memory_accounts = _MemoryAccounts(get_settings().login_throttle_memory_keys)


def _carry_over(client: Any, attempt_key: str, known: bool) -> None:
    """Redis revenu : les échecs gardés en mémoire pendant la panne comptent encore.

    L'état n'est retiré de la mémoire qu'une fois écrit dans Redis : si Redis ne répond
    toujours pas, il reste là pour le repli.
    """
    carried = _memory_accounts.peek(attempt_key, known)
    if not carried or (not carried["fails"] and carried["until"] <= 0):
        return
    pipeline = client.pipeline()
    for at in carried["fails"]:
        pipeline.zadd(attempt_key, {f"memoire-{at!r}": at})
    if carried["fails"]:
        pipeline.expire(attempt_key, math.ceil(_settings_tuple()[1]))
    until_at = float(carried["until"])
    if until_at > _clock():
        pipeline.set(f"{attempt_key}:u", repr(until_at), ex=math.ceil(until_at - _clock()) + 1)
    pipeline.execute()
    _memory_accounts.pop(attempt_key, known)


def begin_attempt(company_slug: str, *, user_id: UUID | None, typed: str) -> AccountAttempt:
    """Réserve un essai de connexion **avant** Argon2, ou lève 429 (ADR 0078, 0088).

    Même réponse que le compte existe ou non, et aucun hachage offert pendant l'attente.
    """
    key, known = account_identity(company_slug, user_id=user_id, typed=typed)
    member = uuid4().hex
    free, horizon, _ = _settings_tuple()
    now = _clock()
    result: tuple[int, float] | None = None
    client = _redis()
    if client is not None:
        try:
            _carry_over(client, key, known)
            raw_fails, raw_until = client.eval(
                _ACCOUNT_BEGIN_LUA, 3, key, f"{key}:p", f"{key}:u", repr(now), member, free, horizon
            )
            result = (int(raw_fails), float(raw_until))
        except Exception:
            result = None
    if result is None:
        _report_degraded()
        result = _memory_accounts.begin(key, known, member, now, free=free, horizon=horizon)
    fails, until_at = result
    if fails < 0:
        raise _wait_error(until_at, now)
    return AccountAttempt(key=key, member=member, known=known)


def record_failure(attempt: AccountAttempt) -> AccountFailure:
    """L'essai a échoué : il compte, et pose l'attente au-delà du seuil."""
    free, horizon, max_wait = _settings_tuple()
    now = _clock()
    key = attempt.key
    client = _redis()
    if client is not None:
        try:
            fails, until_at = client.eval(
                _ACCOUNT_FAIL_LUA,
                3,
                key,
                f"{key}:p",
                f"{key}:u",
                repr(now),
                attempt.member,
                free,
                horizon,
                max_wait,
            )
            return AccountFailure(failures=int(fails), wait_until=float(until_at))
        except Exception:
            pass
    _report_degraded()
    fails, until_at = _memory_accounts.fail(
        key, attempt.known, attempt.member, now, free=free, horizon=horizon, max_wait=max_wait
    )
    return AccountFailure(failures=fails, wait_until=until_at)


def cancel_attempt(attempt: AccountAttempt) -> None:
    """Ni échec ni succès (provisoire expiré, ADR 0078) : l'essai réservé est rendu."""
    _memory_accounts.cancel(attempt.key, attempt.known, attempt.member)
    client = _redis()
    if client is None:
        return
    try:
        client.zrem(f"{attempt.key}:p", attempt.member)
    except Exception:
        _report_degraded()


def reset_account(attempt: AccountAttempt) -> None:
    """Remise à zéro après une connexion réussie."""
    _memory_accounts.pop(attempt.key, attempt.known)
    client = _redis()
    if client is None:
        return
    try:
        client.delete(attempt.key, f"{attempt.key}:p", f"{attempt.key}:u")
    except Exception:
        _report_degraded()
