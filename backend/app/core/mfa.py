"""Primitives de la double authentification de l'administration (ADR 0105).

* **Obligatoire, sans interrupteur** : `PLATFORM_MFA_REQUIRED` est une constante du code.
  `deploy/scripts/check_runtime_env.py` porte la même (test de concordance) et n'accepte
  la porte `COGES_ADMIN_GATE=mfa` qu'avec elle.
* **Secret TOTP chiffré au repos** : AES-256-GCM, nonce aléatoire, données associées =
  l'identifiant du compte (un secret recopié sur une autre ligne ne se déchiffre pas).
* **Codes de secours** : HMAC-SHA-256 sous une clé serveur ; une recherche en base suffit
  à les vérifier (pas dix Argon2), et une copie de la table sans la clé ne sert à rien.
* Les deux clés sont dérivées (HKDF) de `COGES_MFA_ENCRYPTION_KEY` : une seule à garder.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from functools import lru_cache
from typing import Final
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

#: La version déployée impose la double authentification à tout compte de la plateforme.
PLATFORM_MFA_REQUIRED: Final = True

#: Préfixe de format du secret chiffré : une rotation de clé ou d'algorithme se lira.
_FORMAT_V1: Final = b"\x01"
_NONCE_BYTES: Final = 12

RECOVERY_CODE_COUNT: Final = 10
#: Sans 0/O, 1/I/L : un code recopié à la main depuis le papier ne se trompe pas de signe.
_RECOVERY_ALPHABET: Final = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_RECOVERY_HALF: Final = 4
RECOVERY_CODE = re.compile(r"[2-9A-HJKMNP-Z]{4}-?[2-9A-HJKMNP-Z]{4}")


class MfaSecretUnreadableError(Exception):
    """Le secret ne se déchiffre pas : autre clé, autre compte, ou donnée altérée."""


def _derive(info: bytes) -> bytes:
    master = get_settings().require_mfa_encryption_key()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master)


@lru_cache(maxsize=1)
def _encryption_key() -> bytes:
    return _derive(b"coges-mfa-secret-v1")


@lru_cache(maxsize=1)
def _recovery_key() -> bytes:
    return _derive(b"coges-mfa-recovery-v1")


def reset_key_cache() -> None:
    """Après un changement de configuration (tests)."""
    _encryption_key.cache_clear()
    _recovery_key.cache_clear()


def _associated(platform_user_id: UUID) -> bytes:
    return b"coges-platform-user:" + platform_user_id.bytes


def encrypt_secret(secret: str, platform_user_id: UUID) -> bytes:
    nonce = secrets.token_bytes(_NONCE_BYTES)
    sealed = AESGCM(_encryption_key()).encrypt(
        nonce, secret.encode("ascii"), _associated(platform_user_id)
    )
    return _FORMAT_V1 + nonce + sealed


def decrypt_secret(blob: bytes, platform_user_id: UUID) -> str:
    if not blob.startswith(_FORMAT_V1):
        raise MfaSecretUnreadableError()
    nonce = blob[1 : 1 + _NONCE_BYTES]
    try:
        plain = AESGCM(_encryption_key()).decrypt(
            nonce, blob[1 + _NONCE_BYTES :], _associated(platform_user_id)
        )
    except InvalidTag as exc:
        raise MfaSecretUnreadableError() from exc
    return plain.decode("ascii")


def generate_recovery_codes() -> list[str]:
    """Dix codes « ABCD-EFGH » (~40 bits chacun), montrés une fois."""

    def half() -> str:
        return "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_HALF))

    return [f"{half()}-{half()}" for _ in range(RECOVERY_CODE_COUNT)]


def normalise_recovery_code(code: str) -> str | None:
    """Majuscules, sans espace ni tiret ; `None` si la forme n'est pas celle d'un code."""
    cleaned = "".join(code.split()).upper()
    if not RECOVERY_CODE.fullmatch(cleaned):
        return None
    return cleaned.replace("-", "")


def recovery_code_digest(platform_user_id: UUID, normalised: str) -> str:
    """Empreinte stockée : liée au compte, inutilisable sans la clé du serveur."""
    message = platform_user_id.bytes + normalised.encode("ascii")
    return hmac.new(_recovery_key(), message, hashlib.sha256).hexdigest()


def new_opaque_token() -> tuple[str, str]:
    """Jeton aléatoire (intermédiaire de connexion, appareil) et son empreinte SHA-256."""
    raw = secrets.token_urlsafe(32)
    return raw, opaque_token_digest(raw)


def opaque_token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_BROWSERS: Final = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)
_SYSTEMS: Final = (
    ("Android", "Android"),
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Windows", "Windows"),
    ("Mac OS X", "macOS"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)


def browser_label(user_agent: str | None) -> str:
    """« Firefox · Linux » : le navigateur et le système, sans version (une mise à jour
    du navigateur ne fait pas un nouvel appareil)."""
    agent = user_agent or ""
    browser = next((name for marker, name in _BROWSERS if marker in agent), "Navigateur inconnu")
    system = next((name for marker, name in _SYSTEMS if marker in agent), "système inconnu")
    return f"{browser} · {system}"
