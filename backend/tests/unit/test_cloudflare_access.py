"""Vérification du jeton Cloudflare Access (ADR 0104).

Le jeton `Cf-Access-Jwt-Assertion` est signé par Cloudflare (RS256) avec les clés de
l'équipe, publiées sur `https://<équipe>.cloudflareaccess.com/cdn-cgi/access/certs`.
Tout ce qui n'est pas un jeton valide, pour cette application, maintenant, est refusé :
jamais d'ouverture par défaut, même quand le point certs ne répond plus.
"""

from __future__ import annotations

import base64
import hmac
import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from app.core.cloudflare_access import AccessDeniedError, AccessVerifier
from tests.helpers.access_tokens import AUD, CERTS, KEY, OTHER_KEY, TEAM, jwk, token


def _b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


_jwk = jwk
_token = token


class Certs:
    """Point certs simulé : compte les appels, peut tomber en panne."""

    def __init__(self, keys: list[dict[str, Any]]) -> None:
        self.keys = keys
        self.calls = 0
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CERTS
        self.calls += 1
        if self.down:
            return httpx.Response(503)
        return httpx.Response(200, json={"keys": self.keys})


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


def _verifier(certs: Certs, clock: Clock | None = None) -> AccessVerifier:
    return AccessVerifier(
        team_domain=TEAM,
        audience=AUD,
        certs_url=CERTS,
        http=httpx.Client(transport=httpx.MockTransport(certs.handler)),
        clock=clock or time.time,
    )


@pytest.fixture
def certs() -> Certs:
    return Certs([_jwk(KEY, "k1")])


def test_a_valid_token_is_accepted(certs: Certs) -> None:
    assert _verifier(certs).verify(_token()) == "papebothie03@gmail.com"


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda: "", "absent"),
        (lambda: "pas-un-jeton", "illisible"),
        (lambda: _token(OTHER_KEY), "signature d'une autre clé"),
        (lambda: _token(aud=["b" * 64]), "autre application"),
        (lambda: _token(iss="https://autre.cloudflareaccess.com"), "autre équipe"),
        (lambda: _token(exp=int(time.time()) - 120), "expiré"),
        (lambda: _token(nbf=int(time.time()) + 600), "pas encore valable"),
        (lambda: _token(email=""), "sans e-mail"),
        (lambda: _token(kid="inconnue"), "clé inconnue"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_anything_but_a_valid_token_is_refused(
    certs: Certs, make: Callable[[], str], reason: str
) -> None:
    # Jeton tiré à l'exécution : tiré à la collecte, « pas encore valable » ne l'est plus
    # quand la suite complète arrive à ce test, dix minutes plus tard.
    with pytest.raises(AccessDeniedError):
        _verifier(certs).verify(make())


def test_unsigned_and_hmac_tokens_are_refused(certs: Certs) -> None:
    """« alg: none » et HS256 signé avec la clé publique : les deux pièges classiques."""
    claims = jwt.decode(_token(), options={"verify_signature": False})
    unsigned = jwt.encode(claims, None, algorithm="none", headers={"kid": "k1"})
    # PyJWT refuse de signer en HS256 avec une clé publique : le jeton est forgé à la main.
    public_pem = KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signing_input = b".".join(
        _b64(json.dumps(part).encode())
        for part in ({"alg": "HS256", "typ": "JWT", "kid": "k1"}, claims)
    )
    forged = signing_input + b"." + _b64(hmac.new(public_pem, signing_input, "sha256").digest())
    verifier = _verifier(certs)
    for refused in (unsigned, forged.decode()):
        with pytest.raises(AccessDeniedError):
            verifier.verify(refused)


def test_keys_are_fetched_once_then_cached(certs: Certs) -> None:
    verifier = _verifier(certs)
    for _ in range(5):
        verifier.verify(_token())
    assert certs.calls == 1


def test_keys_are_refreshed_after_an_hour(certs: Certs) -> None:
    clock = Clock()
    verifier = _verifier(certs, clock)
    verifier.verify(_token(now=clock.now))
    clock.now += 3601
    verifier.verify(_token(now=clock.now))
    assert certs.calls == 2


def test_an_unknown_key_reloads_the_set_at_most_once_a_minute(certs: Certs) -> None:
    """Cloudflare tourne ses clés : une clé neuve se charge sans attendre l'heure, mais un
    flot de jetons à `kid` inventé ne martèle pas le point certs."""
    clock = Clock()
    verifier = _verifier(certs, clock)
    verifier.verify(_token(now=clock.now))
    clock.now += 61
    for _ in range(3):
        with pytest.raises(AccessDeniedError):
            verifier.verify(_token(kid="k2", now=clock.now))
    assert certs.calls == 2

    certs.keys.append(_jwk(OTHER_KEY, "k2"))
    clock.now += 61
    assert verifier.verify(_token(OTHER_KEY, kid="k2", now=clock.now))
    assert certs.calls == 3


def test_certs_down_without_cached_keys_refuses(certs: Certs) -> None:
    certs.down = True
    with pytest.raises(AccessDeniedError):
        _verifier(certs).verify(_token())


def test_certs_unreachable_refuses() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("injoignable", request=request)

    verifier = AccessVerifier(
        team_domain=TEAM,
        audience=AUD,
        certs_url=CERTS,
        http=httpx.Client(transport=httpx.MockTransport(unreachable)),
    )
    with pytest.raises(AccessDeniedError):
        verifier.verify(_token())


def test_certs_answering_garbage_refuses(certs: Certs) -> None:
    certs.keys = []
    with pytest.raises(AccessDeniedError):
        _verifier(certs).verify(_token())


def test_certs_down_keeps_verified_keys_for_24_hours_at_most(certs: Certs) -> None:
    clock = Clock()
    verifier = _verifier(certs, clock)
    verifier.verify(_token(now=clock.now))
    certs.down = True

    clock.now += 23 * 3600
    assert verifier.verify(_token(now=clock.now))

    clock.now += 3601
    with pytest.raises(AccessDeniedError):
        verifier.verify(_token(now=clock.now))


def test_a_failed_refresh_is_not_retried_on_every_request(certs: Certs) -> None:
    clock = Clock()
    verifier = _verifier(certs, clock)
    verifier.verify(_token(now=clock.now))
    certs.down = True
    clock.now += 3601
    for _ in range(5):
        verifier.verify(_token(now=clock.now))
    assert certs.calls == 2
