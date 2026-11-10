"""Une seule lecture d'un numéro (ADR 0074, 0118) : inscription, connexion, doublons."""

from __future__ import annotations

import pytest

from app.core.phone import normalise_phone, stored_form, to_e164

SAME_NUMBER = (
    "77 000 00 00",
    "770000000",
    "+221770000000",
    "+221 77 000 00 00",
    "00221 77 000 00 00",
    "00221770000000",
    "221770000000",
    "77-000-00-00",
)


@pytest.mark.parametrize("typed", SAME_NUMBER)
def test_every_spelling_gives_the_same_number(typed: str) -> None:
    assert normalise_phone(typed) == "770000000"
    assert to_e164(typed) == "+221770000000"


@pytest.mark.parametrize("typed", SAME_NUMBER)
def test_a_request_number_meets_the_account_number(typed: str) -> None:
    # Ce qui est stocké sur la demande, ramené à la forme du compte, retrouve le compte :
    # un commerçant déjà inscrit ne peut pas ouvrir une seconde boutique.
    assert stored_form(to_e164(typed)) == normalise_phone("77 000 00 00")


def test_a_foreign_number_keeps_its_country_code() -> None:
    assert to_e164("+33 6 12 34 56 78") == "+33612345678"
    assert stored_form("+33612345678") == "33612345678"


@pytest.mark.parametrize("typed", ["", "12", "abc", "1" * 16, None])
def test_what_is_not_a_number_is_refused(typed: str | None) -> None:
    assert to_e164(typed) is None
