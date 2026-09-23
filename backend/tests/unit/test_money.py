"""Noyau partagé : montants, quantités, coûts et taux."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.money import amount, quantity, rate, serialize, unit_cost


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1234567", "1234567.00"),
        (1500, "1500.00"),
        (Decimal("10.005"), "10.01"),  # ROUND_HALF_UP, comme le round() de PostgreSQL
        (Decimal("10.004"), "10.00"),
        (Decimal("-2.345"), "-2.35"),
    ],
)
def test_amount_quantizes_to_two_decimals(value: str | int | Decimal, expected: str) -> None:
    assert amount(value) == Decimal(expected)


def test_quantity_keeps_three_decimals() -> None:
    assert quantity("12.3456") == Decimal("12.346")


def test_unit_cost_keeps_four_decimals() -> None:
    """Précision nécessaire au CMP (§ 4 : coûts unitaires en numeric(14,4))."""
    assert unit_cost("15.00005") == Decimal("15.0001")


def test_rate_keeps_four_decimals() -> None:
    assert rate("0.18") == Decimal("0.1800")


@pytest.mark.parametrize("converter", [amount, quantity, unit_cost, rate])
def test_float_is_always_refused(converter: object) -> None:
    """Décision 15 : aucun flottant sur une donnée financière, nulle part."""
    with pytest.raises(TypeError, match="flottants sont interdits"):
        converter(1234.56)  # type: ignore[operator]


def test_boolean_is_refused() -> None:
    with pytest.raises(TypeError):
        amount(True)


@pytest.mark.parametrize("value", ["", "abc", "1,5"])
def test_invalid_input_raises_value_error(value: str) -> None:
    with pytest.raises(ValueError, match="valeur numérique invalide"):
        amount(value)


def test_non_finite_is_refused() -> None:
    with pytest.raises(ValueError, match="non finie"):
        amount(Decimal("NaN"))


def test_serialize_returns_a_plain_string() -> None:
    """Dans le JSON, un montant est une **chaîne** : jamais un nombre flottant."""
    serialized = serialize(amount("1234567"))
    assert serialized == "1234567.00"
    assert isinstance(serialized, str)


def test_serialize_never_uses_scientific_notation() -> None:
    assert serialize(amount("0.001")) == "0.00"
    assert serialize(unit_cost("0.00001")) == "0.0000"
