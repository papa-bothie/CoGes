"""Vérification du jeton Cloudflare Access de l'administration (ADR 0104).

Cloudflare Access se place devant `admin.<domaine>` : il ne laisse passer qu'une personne
de la règle (une adresse e-mail) et joint à chaque requête un jeton signé,
`Cf-Access-Jwt-Assertion`. L'API le vérifie elle-même : arriver « par le bon chemin » ne
suffit pas, il faut un jeton valide, pour cette application, maintenant.

* signature RS256 seule, avec les clés publiques de l'équipe
  (`https://<équipe>.cloudflareaccess.com/cdn-cgi/access/certs`) ;
* `aud` contient l'AUD de l'application, `iss` est l'équipe, `exp`/`nbf` tenus ;
* une adresse e-mail dans le jeton (une personne, pas un jeton de service).

Les clés sont gardées une heure. Une clé inconnue (Cloudflare les tourne) recharge le jeu,
au plus une fois par minute. Si le point certs ne répond plus, les clés déjà vérifiées
servent encore 24 h, puis tout est refusé ; sans clé en cache, refus immédiat. Jamais
d'ouverture par défaut.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import httpx
import jwt

from app.core.config import get_settings

logger = logging.getLogger("coges.cloudflare_access")

ACCESS_HEADER = "cf-access-jwt-assertion"
REFRESH_SECONDS = 3600
STALE_SECONDS = 24 * 3600
#: Délai minimal entre deux chargements du jeu de clés, réussis ou non.
RETRY_SECONDS = 60
#: Écart d'horloge toléré entre Cloudflare et le VPS.
LEEWAY_SECONDS = 30
FETCH_TIMEOUT_SECONDS = 5.0


class AccessDeniedError(Exception):
    """Jeton absent ou invalide ; le motif va au journal, jamais au client."""


def certs_url_for(team_domain: str) -> str:
    return f"https://{team_domain}/cdn-cgi/access/certs"


@dataclass
class AccessVerifier:
    team_domain: str
    audience: str
    certs_url: str
    http: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=FETCH_TIMEOUT_SECONDS))
    clock: Callable[[], float] = time.time
    _keys: dict[str, Any] = field(default_factory=dict, init=False)
    #: Dernier chargement réussi, et dernière tentative (réussie ou non).
    _fetched_at: float | None = field(default=None, init=False)
    _attempted_at: float | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def verify(self, token: str) -> str:
        """Adresse e-mail du jeton, ou `AccessDeniedError`."""
        if not token:
            raise AccessDeniedError("jeton absent")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AccessDeniedError("jeton illisible") from exc
        if header.get("alg") != "RS256":
            raise AccessDeniedError(f"algorithme refusé : {header.get('alg')!r}")
        key = self._key(str(header.get("kid", "")))
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=f"https://{self.team_domain}",
                leeway=LEEWAY_SECONDS,
                # Le temps est vérifié plus bas, avec l'horloge du vérificateur.
                options={
                    "require": ["exp", "iat", "aud", "iss"],
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise AccessDeniedError(f"jeton refusé : {type(exc).__name__}") from exc
        # Un seul « maintenant » pour les clés et le jeton (et une horloge injectable).
        now = self.clock()
        if float(claims["exp"]) + LEEWAY_SECONDS < now:
            raise AccessDeniedError("jeton expiré")
        if float(claims.get("nbf", claims["iat"])) - LEEWAY_SECONDS > now:
            raise AccessDeniedError("jeton pas encore valable")
        email = claims.get("email")
        if not isinstance(email, str) or not email:
            raise AccessDeniedError("jeton sans adresse e-mail")
        return email

    def _key(self, kid: str) -> Any:
        with self._lock:
            now = self.clock()
            stale = self._fetched_at is None or now - self._fetched_at >= REFRESH_SECONDS
            if stale or kid not in self._keys:
                self._refresh(now)
            if self._fetched_at is None or now - self._fetched_at >= STALE_SECONDS:
                raise AccessDeniedError("aucune clé Cloudflare vérifiée depuis 24 h")
            key = self._keys.get(kid)
        if key is None:
            raise AccessDeniedError("clé de signature inconnue")
        return key

    def _refresh(self, now: float) -> None:
        if self._attempted_at is not None and now - self._attempted_at < RETRY_SECONDS:
            return
        self._attempted_at = now
        try:
            response = self.http.get(self.certs_url)
            response.raise_for_status()
            keys = {
                str(jwk.key_id): jwk.key
                for jwk in jwt.PyJWKSet.from_dict(response.json()).keys
                if jwk.key_id and jwk.algorithm_name == "RS256"
            }
        except (httpx.HTTPError, ValueError, jwt.PyJWTError) as exc:
            logger.warning(
                "clés Cloudflare Access injoignables", extra={"reason": type(exc).__name__}
            )
            return
        if not keys:
            logger.warning("clés Cloudflare Access vides", extra={"reason": "no_rs256_key"})
            return
        self._keys = keys
        self._fetched_at = now


@lru_cache
def get_access_verifier() -> AccessVerifier | None:
    """Vérificateur du processus, ou `None` quand Access n'est pas configuré."""
    settings = get_settings()
    if not settings.access_team_domain or not settings.access_aud:
        return None
    return AccessVerifier(
        team_domain=settings.access_team_domain,
        audience=settings.access_aud,
        certs_url=settings.access_certs_url or certs_url_for(settings.access_team_domain),
    )
