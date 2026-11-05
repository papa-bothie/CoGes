"""Montant en lettres et montants du reçu, identiques au front (ADR 0113)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.display import amount, amount_in_words, figure, number_in_words

CASES = [
    (0, "zéro"),
    (1, "un"),
    (16, "seize"),
    (17, "dix-sept"),
    (21, "vingt et un"),
    (71, "soixante et onze"),
    (80, "quatre-vingts"),
    (81, "quatre-vingt-un"),
    (91, "quatre-vingt-onze"),
    (100, "cent"),
    (200, "deux cents"),
    (201, "deux cent un"),
    (1000, "mille"),
    (2000, "deux mille"),
    (25000, "vingt-cinq mille"),
    (80000, "quatre-vingt mille"),
    (200000, "deux cent mille"),
    (1000000, "un million"),
    (2500000, "deux millions cinq cent mille"),
    (1001000000, "un milliard un million"),
]


@pytest.mark.parametrize(("value", "words"), CASES)
def test_number_in_words_matches_the_front(value: int, words: str) -> None:
    assert number_in_words(value) == words


def test_amount_in_words() -> None:
    assert amount_in_words(Decimal("25000.00")) == "vingt-cinq mille francs CFA"
    assert amount_in_words(Decimal("1.00")) == "un franc CFA"


def test_receipt_amounts_use_a_full_non_breaking_space() -> None:
    assert amount(Decimal("87500.00")) == "87 500 F"
    assert figure(Decimal("1234567.49")) == "1 234 567"


def test_the_attachment_name_drops_quotes_backslashes_and_control_characters() -> None:
    """`Content-Disposition` : un nom de fichier ne casse jamais l'en-tête (ADR 0113)."""
    from app.core.pdf import attachment

    header = attachment('Re"çu\\ n°\r\n1\x00\t2.pdf')
    ascii_part = header.split("filename=", 1)[1].split(";", 1)[0]
    assert ascii_part == '"Recu n12.pdf"', header
    assert "\r" not in header and "\n" not in header and "\x00" not in header
    assert "%22" not in header and "%5C" not in header, "ni guillemet ni barre en UTF-8 non plus"
    assert attachment('""').startswith('attachment; filename="document.pdf"')
