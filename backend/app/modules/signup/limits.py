"""Limites de l'inscription (ADR 0118), dans Redis, **fermées** si Redis manque.

Aucune valeur personnelle dans une clé : l'IP, le numéro et l'e-mail n'y entrent que par
un HMAC (`COGES_SIGNUP_IP_HASH_KEY`). Un sha256 sans clé d'une IPv4 se retrouve en
quelques minutes (4 milliards d'adresses) ; avec la clé, non.

Clés (déclarées dans `tests/tenancy/test_redis_keys_isolation.py`), toutes avec TTL :

* `coges:signup:<portée>:<hmac>:<fenêtre>` — compteurs par IP (heure, jour), numéro et
  e-mail (jour), renvois par e-mail (jour) ;
* `coges:signup:global:h:<fenêtre>` et `coges:signup:auto:d:<fenêtre>` — plafond global
  par heure, demandes automatiques du jour ;
* `coges:signup:resend:<hmac>` — délai entre deux renvois (écrite seulement si absente, avec durée).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import time
from typing import Any

from app.core import cache
from app.core.config import get_settings
from app.core.errors import RateLimitedError, SignupUnavailableError

HOUR = 3600
DAY = 86_400
PREFIX = f"{cache.NAMESPACE}:signup"


def _clock() -> float:
    return time.time()


def fingerprint(kind: str, value: str) -> str:
    """HMAC-SHA256 d'une valeur, préfixé par sa nature (une IP n'égale jamais un numéro)."""
    key = get_settings().require_signup_ip_hash_key()
    return hmac.new(key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def ip_fingerprint(ip: str | None) -> str | None:
    """Empreinte de l'IP stockée sur la demande ; une IPv6 compte par son /64 (ADR 0088)."""
    if not ip:
        return None
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    value = (
        str(ipaddress.ip_network(f"{address}/64", strict=False).network_address) + "/64"
        if address.version == 6
        else str(address)
    )
    return fingerprint("ip", value)


def _client() -> Any:
    client = cache.get_client()
    if client is None:
        raise SignupUnavailableError()
    return client


def _incr(client: Any, key: str, ttl: int) -> int:
    try:
        pipeline = client.pipeline()
        pipeline.incr(key)
        pipeline.expire(key, ttl)
        return int(pipeline.execute()[0])
    except Exception as exc:
        raise SignupUnavailableError() from exc


def _window_key(scope: str, period: int, digest: str | None = None) -> tuple[str, int]:
    now = int(_clock())
    window = now // period
    middle = f"{scope}:{digest}" if digest else scope
    return f"{PREFIX}:{middle}:{window}", period - (now % period)


def check_request(*, ip_hash: str | None, phone: str, email: str | None) -> None:
    """Compte une demande ; 429 au-delà d'une limite, 503 si Redis manque."""
    settings = get_settings()
    client = _client()
    counters: list[tuple[str, int, str | None, int]] = [
        ("global:h", HOUR, None, settings.signup_global_per_hour),
        ("phone:d", DAY, fingerprint("phone", phone), settings.signup_phone_per_day),
    ]
    if ip_hash is not None:
        counters += [
            ("ip:h", HOUR, ip_hash, settings.signup_ip_per_hour),
            ("ip:d", DAY, ip_hash, settings.signup_ip_per_day),
        ]
    if email is not None:
        counters.append(
            ("email:d", DAY, fingerprint("email", email), settings.signup_email_per_day)
        )
    for scope, period, digest, limit in counters:
        key, retry_after = _window_key(scope, period, digest)
        if _incr(client, key, period * 2) > limit:
            raise RateLimitedError(retry_after, scope=f"signup_{scope.split(':')[0]}")


def take_automatic_slot() -> bool:
    """Une demande de plus par le lien automatique aujourd'hui ? Faux au-delà du plafond :
    la demande passe par l'équipe (jamais un refus)."""
    client = _client()
    key, _ = _window_key("auto:d", DAY)
    return _incr(client, key, DAY * 2) <= get_settings().signup_auto_per_day


def check_resend(email: str) -> None:
    """Un renvoi par minute et cinq par jour et par adresse ; 429 au-delà."""
    settings = get_settings()
    client = _client()
    digest = fingerprint("email", email)
    try:
        allowed = client.set(
            f"{PREFIX}:resend:{digest}", "1", nx=True, ex=settings.signup_resend_interval_seconds
        )
    except Exception as exc:
        raise SignupUnavailableError() from exc
    if not allowed:
        raise RateLimitedError(settings.signup_resend_interval_seconds, scope="signup_resend")
    key, retry_after = _window_key("resend:d", DAY, digest)
    if _incr(client, key, DAY * 2) > settings.signup_resend_per_day:
        raise RateLimitedError(retry_after, scope="signup_resend")
