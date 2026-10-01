"""Formatage d'affichage des textes composés côté serveur (ADR 0057).

Mêmes sorties que le front (`frontend/lib/format/money.test.ts`, `qty.test.ts`) : un
texte de notification et l'écran écrivent un montant, une quantité, une date de la
même façon.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.display import dmy, fcfa, number, qty

NNBSP = "\u202f"  # espace fine insécable : milliers
NBSP = "\u00a0"  # espace insécable : avant l'unité


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1234567.00", f"1{NNBSP}234{NNBSP}567{NBSP}FCFA"),
        ("1234567.50", f"1{NNBSP}234{NNBSP}568{NBSP}FCFA"),
        ("1234567.49", f"1{NNBSP}234{NNBSP}567{NBSP}FCFA"),
        ("999.5", f"1{NNBSP}000{NBSP}FCFA"),
        ("750.00", f"750{NBSP}FCFA"),
        ("-2500.00", f"-2{NNBSP}500{NBSP}FCFA"),
    ],
)
def test_amounts_are_whole_fcfa_with_thin_spaces(value: str, expected: str) -> None:
    assert fcfa(Decimal(value)) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.000", "1"),
        ("12.500", "12,5"),
        ("1500.000", f"1{NNBSP}500"),
        ("0.125", "0,125"),
        ("3", "3"),
    ],
)
def test_quantities_drop_useless_zeros(value: str, expected: str) -> None:
    assert qty(Decimal(value)) == expected


def test_dates_and_numbers_are_french() -> None:
    assert dmy(date(2026, 9, 17)) == "17/09/2026"
    assert number(Decimal("10864")) == f"10{NNBSP}864"
    assert number(Decimal("0.036"), 3) == "0,036"
