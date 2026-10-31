"""Code lu par la caméra ou la douchette (prompt 33, ADR 0106).

Un code-barres EAN/UPC porte sa clé de contrôle : un code faux est refusé plutôt que
cherché. Un UPC-A (12 chiffres) et l'EAN-13 qui le précède d'un 0 désignent le même
article ; un UPC-E (8 chiffres) est la forme courte d'un UPC-A.
"""

from __future__ import annotations

import pytest

from app.core.codes import scanned_code_candidates


def test_spaces_are_removed_everywhere() -> None:
    assert scanned_code_candidates("  4006 3813 33931 \n") == ("4006381333931",)


def test_upc_a_and_its_ean_13_are_the_same_code() -> None:
    assert scanned_code_candidates("036000291452") == ("036000291452", "0036000291452")
    assert scanned_code_candidates("0036000291452") == ("0036000291452", "036000291452")


def test_upc_e_also_finds_its_upc_a() -> None:
    assert scanned_code_candidates("04252614") == ("04252614", "042100005264", "0042100005264")


def test_ean_8_is_checked() -> None:
    assert scanned_code_candidates("96385074") == ("96385074",)
    assert scanned_code_candidates("96385075") is None


@pytest.mark.parametrize("wrong", ["4006381333932", "036000291453", "00036000291453"])
def test_a_wrong_check_digit_is_refused(wrong: str) -> None:
    assert scanned_code_candidates(wrong) is None


def test_gtin_14_finds_the_shorter_forms() -> None:
    assert scanned_code_candidates("00036000291452") == (
        "00036000291452",
        "0036000291452",
        "036000291452",
    )


def test_other_codes_are_kept_as_typed() -> None:
    """Code 128 ou référence : pas de clé à vérifier, la référence se cherche en majuscules."""
    assert scanned_code_candidates("art-0001") == ("art-0001", "ART-0001")
    assert scanned_code_candidates("12345") == ("12345",)


@pytest.mark.parametrize("empty", ["", "   ", "1" * 65])
def test_nothing_or_too_long_is_refused(empty: str) -> None:
    assert scanned_code_candidates(empty) is None
