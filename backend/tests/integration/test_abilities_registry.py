"""Registre de la grille « Qui peut faire quoi » (prompt 28, C3, ADR 0099).

Le gérant ne peut retirer que ce que la grille montre : tout droit du catalogue, sauf
gérer les rôles (`roles:`), appartient donc à au moins une ligne, et les rôles par défaut
sont exactement une somme de lignes — sinon le premier enregistrement de la grille leur
retirerait des droits sans prévenir. Ces tests échouent dès qu'un droit nouveau arrive au
catalogue sans ligne.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.modules.rbac.matrix import (
    ABILITIES,
    ACCOUNTANT_PERMISSIONS,
    LOCKED_ABILITIES,
    SALESPERSON_PERMISSIONS,
)

pytestmark = pytest.mark.integration

#: Hors grille : qui gère les rôles peut se donner tout le reste (ADR 0075, 0088).
OUTSIDE_THE_GRID = ("roles:",)


def _catalogue(session_factory: sessionmaker[Any]) -> set[str]:
    with session_factory() as session:
        return set(session.execute(text("SELECT code FROM permissions")).scalars().all())


def _union(keys: set[str]) -> set[str]:
    return set().union(*(ABILITIES[key][1] for key in keys))


def test_every_right_of_the_catalogue_is_in_a_line(session_factory: sessionmaker[Any]) -> None:
    grid = _union(set(ABILITIES))
    missing = sorted(
        code
        for code in _catalogue(session_factory)
        if not code.startswith(OUTSIDE_THE_GRID) and code not in grid
    )
    assert missing == [], f"droits qu'aucune ligne de la grille ne montre : {missing}"


def test_no_line_names_an_unknown_right(session_factory: sessionmaker[Any]) -> None:
    unknown = sorted(_union(set(ABILITIES)) - _catalogue(session_factory))
    assert unknown == []


@pytest.mark.parametrize(
    ("role", "rights"),
    [("vendeur", SALESPERSON_PERMISSIONS), ("comptable", ACCOUNTANT_PERMISSIONS)],
)
def test_each_default_role_is_exactly_a_sum_of_lines(role: str, rights: frozenset[str]) -> None:
    checked = {key for key, (_, needed) in ABILITIES.items() if needed <= rights}
    assert _union(checked) == set(rights), role


def test_locked_lines() -> None:
    assert {"base", "manage_people", "shop_settings"} == LOCKED_ABILITIES
