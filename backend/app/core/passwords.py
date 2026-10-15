"""Mots de passe provisoires lisibles (maquette v2, écran 24b ; ADR 0074).

« BAOBAB-4821-KORA » : deux mots simples et quatre chiffres, faciles à dicter au
téléphone et à recopier. Au moins 12 caractères, comme tout mot de passe (`UserCreate`).
Le compte doit le changer à sa première connexion (`must_change_password`).
"""

from __future__ import annotations

import secrets

_WORDS = (
    "ACACIA",
    "BAOBAB",
    "CAURIS",
    "DJEMBE",
    "FONIO",
    "GOREE",
    "KORA",
    "LAGUNE",
    "MANGUE",
    "NIAYE",
    "PIROGUE",
    "SABAR",
    "SAHEL",
    "TERANGA",
    "THIOF",
    "WALO",
)


def readable_password() -> str:
    """Un mot de passe provisoire tiré au hasard par `secrets` (jamais `random`)."""
    first, second = secrets.choice(_WORDS), secrets.choice(_WORDS)
    digits = f"{secrets.randbelow(10_000):04d}"
    return f"{first}-{digits}-{second}"
