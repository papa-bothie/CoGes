"""Codes à usage unique basés sur le temps (TOTP, RFC 6238), sans bibliothèque (ADR 0105).

Paramètres fixes, ceux que toutes les applications Authenticator lisent sans réglage :
HMAC-SHA-1, pas de 30 s, 6 chiffres. Un code est accepté pour le pas courant, le
précédent ou le suivant (±1 pas : horloges du téléphone et du serveur décalées), et
**seulement** pour un pas plus récent que le dernier accepté : le même code ne sert
jamais deux fois, même dans sa fenêtre (anti-rejeu, `platform_users.mfa_last_step`).

Le calcul tient en quelques lignes de la bibliothèque standard ; il est vérifié contre
les vecteurs de l'annexe B de la RFC 6238 (`tests/unit/test_totp.py`).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse
from typing import Final

STEP_SECONDS: Final = 30
DIGITS: Final = 6
#: Pas acceptés de part et d'autre du pas courant.
TOLERANCE_STEPS: Final = 1
#: 160 bits : la longueur de clé recommandée par la RFC 4226 pour HMAC-SHA-1.
SECRET_BYTES: Final = 20
ISSUER: Final = "CoGes Administration"

#: Horloge substituable par les tests.
_clock = time.time


def generate_secret() -> str:
    """Secret aléatoire en base32 sans remplissage (32 caractères), comme l'attendent
    les applications."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def current_step(now: float | None = None) -> int:
    return int((_clock() if now is None else now) // STEP_SECONDS)


def code_at(secret: str, step: int, *, digits: int = DIGITS) -> str:
    """Code du pas `step` (RFC 4226 § 5.3, troncature dynamique)."""
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def normalise(code: str) -> str:
    """Espaces tolérés (« 123 456 ») ; rien d'autre n'est réécrit."""
    return "".join(code.split())


def matching_step(
    secret: str, code: str, *, last_step: int | None, now: float | None = None
) -> int | None:
    """Pas auquel `code` correspond, s'il est accepté ; `None` sinon.

    Chaque pas candidat est comparé à temps constant, et tous le sont : la durée ne dit
    pas lequel a correspondu.
    """
    typed = normalise(code)
    if len(typed) != DIGITS or not typed.isdigit():
        return None
    step = current_step(now)
    found: int | None = None
    for candidate in range(step - TOLERANCE_STEPS, step + TOLERANCE_STEPS + 1):
        if hmac.compare_digest(code_at(secret, candidate), typed) and found is None:
            found = candidate
    if found is None or (last_step is not None and found <= last_step):
        return None
    return found


def provisioning_uri(secret: str, account: str) -> str:
    """Lien `otpauth://` lu par le QR code (format de Google Authenticator)."""
    label = urllib.parse.quote(f"{ISSUER}:{account}")
    query = urllib.parse.urlencode(
        {
            "secret": secret,
            "issuer": ISSUER,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP_SECONDS,
        },
        quote_via=urllib.parse.quote,
    )
    return f"otpauth://totp/{label}?{query}"
