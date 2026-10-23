"""Primitives de sécurité : hachage des mots de passe et jetons.

Décision 16 : Argon2id pour les mots de passe, JWT courts pour l'accès, refresh
**rotatif**. Le secret de signature vient de la configuration, jamais du code.

Le refresh token n'est pas un JWT : c'est un secret opaque de 256 bits, stocké
**haché** dans `auth_sessions`. Un jeton volé en base est donc inutilisable, et la
révocation est immédiate puisqu'elle se lit en base à chaque rafraîchissement.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import AuthenticationRequiredError

ALGORITHM: Final = "HS256"
ACCESS_TOKEN_TYPE: Final = "access"
#: Deux familles de jetons, jamais interchangeables (ADR 0089) : chacune exige son
#: `typ` **et** son audience. Un jeton commerçant n'ouvre rien sous `/platform`, un
#: jeton plateforme rien ailleurs, même signés par la même clé.
TENANT_AUDIENCE: Final = "coges-tenant"
PLATFORM_TOKEN_TYPE: Final = "platform_access"
PLATFORM_AUDIENCE: Final = "coges-platform"
REFRESH_TOKEN_BYTES: Final = 32

# Paramètres Argon2id : valeurs par défaut d'argon2-cffi, adaptées à une API web.
_password_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Hache un mot de passe en Argon2id."""
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Vérifie un mot de passe. Ne lève jamais : renvoie False en cas d'échec."""
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Indique si le hachage doit être refait (paramètres Argon2 obsolètes)."""
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@dataclass(frozen=True, slots=True)
class AccessClaims:
    """Contenu vérifié d'un jeton d'accès."""

    user_id: UUID
    company_id: UUID
    token_id: UUID


def create_access_token(user_id: UUID, company_id: UUID) -> tuple[str, int]:
    """Émet un jeton d'accès court. Renvoie (jeton, durée de vie en secondes)."""
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = settings.jwt_access_ttl_seconds
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "typ": ACCESS_TOKEN_TYPE,
        "aud": TENANT_AUDIENCE,
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)
    return token, ttl


def decode_access_token(token: str) -> AccessClaims:
    """Vérifie signature et expiration, puis renvoie les claims.

    Les claims ne font **pas** autorité sur le tenant : `deps.py` relit l'utilisateur
    en base, et la RLS refuse la ligne si le couple (utilisateur, entreprise) ne
    correspond pas.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            audience=TENANT_AUDIENCE,
            options={"require": ["exp", "sub", "typ", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationRequiredError("Jeton d'accès invalide ou expiré.") from exc

    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        raise AuthenticationRequiredError("Type de jeton inattendu.")

    try:
        return AccessClaims(
            user_id=UUID(payload["sub"]),
            company_id=UUID(payload["company_id"]),
            token_id=UUID(payload["jti"]),
        )
    except (KeyError, ValueError) as exc:
        raise AuthenticationRequiredError("Jeton d'accès malformé.") from exc


@dataclass(frozen=True, slots=True)
class PlatformClaims:
    """Contenu vérifié d'un jeton de l'administration (ADR 0089). Aucune entreprise."""

    platform_user_id: UUID
    platform_role: str
    token_id: UUID


def create_platform_access_token(platform_user_id: UUID, platform_role: str) -> tuple[str, int]:
    """Jeton d'accès de l'administration : `platform_role` à la place de `company_id`."""
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = settings.jwt_access_ttl_seconds
    payload: dict[str, Any] = {
        "sub": str(platform_user_id),
        "platform_role": platform_role,
        "typ": PLATFORM_TOKEN_TYPE,
        "aud": PLATFORM_AUDIENCE,
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)
    return token, ttl


def decode_platform_token(token: str) -> PlatformClaims:
    """Vérifie un jeton de l'administration. Comme pour un commerçant, le rôle porté par
    le jeton ne fait pas autorité : `deps.py` relit le compte en base."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            audience=PLATFORM_AUDIENCE,
            options={"require": ["exp", "sub", "typ", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationRequiredError("Jeton d'accès invalide ou expiré.") from exc

    if payload.get("typ") != PLATFORM_TOKEN_TYPE:
        raise AuthenticationRequiredError("Type de jeton inattendu.")
    try:
        return PlatformClaims(
            platform_user_id=UUID(payload["sub"]),
            platform_role=str(payload["platform_role"]),
            token_id=UUID(payload["jti"]),
        )
    except (KeyError, ValueError) as exc:
        raise AuthenticationRequiredError("Jeton d'accès malformé.") from exc


def announces_platform_audience(token: str) -> bool:
    """Le jeton **se dit** destiné à l'administration — sans rien prouver.

    Lecture non vérifiée, qui ne sert qu'à choisir la porte d'une route à deux entrées
    (`/system/workers`, ADR 0090) : la porte choisie vérifie ensuite le jeton en entier.
    Un jeton de l'équipe périmé reçoit ainsi 401 (et se rafraîchit), pas le 404 d'un
    jeton d'exploitation non configuré.
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return False
    audience = claims.get("aud")
    return audience == PLATFORM_AUDIENCE or (
        isinstance(audience, list) and PLATFORM_AUDIENCE in audience
    )


def generate_refresh_token() -> tuple[str, str]:
    """Crée un refresh token opaque. Renvoie (valeur en clair, empreinte à stocker)."""
    raw_token = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    return raw_token, hash_refresh_token(raw_token)


def hash_refresh_token(raw_token: str) -> str:
    """Empreinte d'un refresh token.

    SHA-256 suffit ici, contrairement à un mot de passe : la valeur est un secret
    aléatoire de 256 bits, donc hors de portée d'une attaque par dictionnaire.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    """Date d'expiration d'un refresh token, à partir de la configuration."""
    return datetime.now(UTC) + timedelta(seconds=get_settings().jwt_refresh_ttl_seconds)
