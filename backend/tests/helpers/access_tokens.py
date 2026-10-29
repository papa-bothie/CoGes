"""Faux jetons Cloudflare Access, signés par une clé de test (ADR 0104).

Sert aux tests (clé tirée au chargement) et aux parcours e2e de l'administration :

    python -m tests.helpers.access_tokens DOSSIER

écrit `DOSSIER/cdn-cgi/access/certs` (le jeu de clés public, servi en local par
`deploy/scripts/e2e.sh api`) et `DOSSIER/token` (un jeton valable 24 h pour l'équipe et
l'AUD ci-dessous). Un jeton de moins de 12 h est gardé : l'API e2e qui tourne déjà garde
ses clés en cache, et la configuration de Playwright est relue par chaque processus.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

TEAM = "coges-test.cloudflareaccess.com"
AUD = "a" * 64
CERTS = f"https://{TEAM}/cdn-cgi/access/certs"
EMAIL = "papebothie03@gmail.com"


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KEY = new_key()
OTHER_KEY = new_key()


def jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    public: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    return {**public, "kid": kid, "alg": "RS256", "use": "sig"}


def token(
    key: rsa.RSAPrivateKey = KEY,
    *,
    kid: str = "k1",
    now: float | None = None,
    lifetime: int = 3600,
    **claims: Any,
) -> str:
    issued = int(now if now is not None else time.time())
    payload: dict[str, Any] = {
        "aud": [AUD],
        "iss": f"https://{TEAM}",
        "email": EMAIL,
        "iat": issued,
        "nbf": issued,
        "exp": issued + lifetime,
        "sub": "f0f0f0f0",
        **claims,
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


FIXTURE_REUSE_SECONDS = 12 * 3600


def write_fixture(directory: Path) -> None:
    """Jeu de clés et jeton des parcours e2e ; une clé neuve quand le jeton vieillit.

    L'identifiant de clé change avec la clé : une API qui tourne encore la recharge.
    """
    certs = directory / "cdn-cgi" / "access" / "certs"
    saved = directory / "token"
    fresh = saved.is_file() and time.time() - saved.stat().st_mtime < FIXTURE_REUSE_SECONDS
    if fresh and certs.is_file():
        return
    key = new_key()
    kid = hashlib.sha256(json.dumps(jwk(key, "")).encode()).hexdigest()[:16]
    certs.parent.mkdir(parents=True, exist_ok=True)
    certs.write_text(json.dumps({"keys": [jwk(key, kid)]}), encoding="utf-8")
    saved.write_text(token(key, kid=kid, lifetime=24 * 3600), encoding="utf-8")


if __name__ == "__main__":
    write_fixture(Path(sys.argv[1]))
