"""Numéros de téléphone ramenés à leurs chiffres (ADR 0074).

Un numéro sénégalais se tape de bien des façons (« 77 123 45 67 », « +221 771234567 »,
« 00221 77 123 45 67 ») : on garde les chiffres, sans l'indicatif 221 devant un numéro à
neuf chiffres. C'est la forme stockée sur `users.phone` et cherchée à la connexion.
"""

from __future__ import annotations

import re

#: Indicatif du Sénégal, retiré devant un numéro national à neuf chiffres.
SENEGAL_PREFIX = "221"
NATIONAL_DIGITS = 9
MIN_DIGITS = 6
MAX_DIGITS = 15


def normalise_phone(raw: str | None) -> str | None:
    """Chiffres du numéro, ou `None` s'il n'en est pas un (trop court, trop long)."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith(SENEGAL_PREFIX) and len(digits) == len(SENEGAL_PREFIX) + NATIONAL_DIGITS:
        digits = digits[len(SENEGAL_PREFIX) :]
    if not MIN_DIGITS <= len(digits) <= MAX_DIGITS:
        return None
    return digits


def to_e164(raw: str | None) -> str | None:
    """Le même numéro au format international (`+221771234567`), pour les demandes
    d'inscription et les liens `wa.me` (ADR 0118).

    Construit sur `normalise_phone` : il n'existe qu'**une** lecture d'un numéro, si bien
    que « 77 123 45 67 », « +221 77 123 45 67 » et « 00221 771234567 » désignent toujours
    le même commerçant, à l'inscription comme à la connexion.
    """
    digits = normalise_phone(raw)
    if digits is None:
        return None
    if len(digits) == NATIONAL_DIGITS:
        return f"+{SENEGAL_PREFIX}{digits}"
    return f"+{digits}"


def stored_form(e164: str | None) -> str | None:
    """Le numéro d'une demande, ramené à la forme de `users.phone` (activation, doublons)."""
    return normalise_phone(e164)
