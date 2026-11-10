"""Version des textes légaux en vigueur (prompt 36, ADR 0117).

Une seule valeur pour les deux textes du front (`frontend/content/legal/conditions.md` et
`confidentialite.md`) : la plus récente de leurs lignes `<!-- version: AAAA-MM-JJ -->`.
`tests/unit/test_legal_version.py` vérifie l'égalité, pour qu'un texte republié sans
changer cette constante fasse échouer la CI.

Changer cette valeur redemande l'acceptation à tout le monde : `core/deps.py` refuse
toute route (sauf l'identité et l'acceptation) à un compte dont la version acceptée
diffère, comme pour le mot de passe provisoire (ADR 0074).
"""

from __future__ import annotations

from typing import Final

LEGAL_VERSION: Final = "2026-12-01"

#: Les seules routes ouvertes à un compte qui n'a pas accepté la version courante.
LEGAL_ACCEPTANCE_PATHS: Final = frozenset({"/api/v1/auth/me", "/api/v1/auth/legal-acceptance"})


def acceptance_required(accepted_version: str | None) -> bool:
    """Vrai tant que la personne n'a pas accepté **la** version courante."""
    return accepted_version != LEGAL_VERSION
