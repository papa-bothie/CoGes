"""TOTP maison (ADR 0105) : vecteurs de la RFC 6238, tolérance d'un pas, anti-rejeu."""

from __future__ import annotations

import base64
import urllib.parse

import pytest

from app.core import totp

#: Annexe B de la RFC 6238, HMAC-SHA-1 : la clé ASCII « 12345678901234567890 ».
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize(("moment", "expected"), RFC_VECTORS)
def test_rfc_6238_vectors(moment: int, expected: str) -> None:
    step = totp.current_step(moment)
    assert totp.code_at(RFC_SECRET, step, digits=8) == expected
    # Six chiffres : les six derniers du code à huit (même troncature).
    assert totp.code_at(RFC_SECRET, step) == expected[-6:]


def test_a_secret_is_160_bits_of_base32_without_padding() -> None:
    secret = totp.generate_secret()
    assert len(secret) == 32 and "=" not in secret
    assert len(base64.b32decode(secret)) == 20
    assert totp.generate_secret() != secret


def test_one_step_either_side_is_accepted_two_are_not() -> None:
    secret = totp.generate_secret()
    now = 1_800_000_000.0
    step = totp.current_step(now)
    for accepted in (step - 1, step, step + 1):
        code = totp.code_at(secret, accepted)
        assert totp.matching_step(secret, code, last_step=None, now=now) == accepted
    for refused in (step - 2, step + 2):
        code = totp.code_at(secret, refused)
        assert totp.matching_step(secret, code, last_step=None, now=now) is None


def test_a_code_is_never_accepted_twice() -> None:
    secret = totp.generate_secret()
    now = 1_800_000_000.0
    step = totp.current_step(now)
    code = totp.code_at(secret, step)
    assert totp.matching_step(secret, code, last_step=step - 1, now=now) == step
    # Même code, même fenêtre : le pas est déjà consommé.
    assert totp.matching_step(secret, code, last_step=step, now=now) is None
    # Le code du pas précédent non plus : il est plus ancien que le dernier accepté.
    previous = totp.code_at(secret, step - 1)
    assert totp.matching_step(secret, previous, last_step=step, now=now) is None
    # Le suivant, si.
    following = totp.code_at(secret, step + 1)
    assert totp.matching_step(secret, following, last_step=step, now=now) == step + 1


@pytest.mark.parametrize("typed", ["", "12345", "1234567", "abcdef", "12 34 5x"])
def test_malformed_codes_are_refused(typed: str) -> None:
    assert totp.matching_step(totp.generate_secret(), typed, last_step=None) is None


def test_spaces_inside_a_code_are_tolerated() -> None:
    secret = totp.generate_secret()
    code = totp.code_at(secret, totp.current_step())
    assert totp.matching_step(secret, f"{code[:3]} {code[3:]}", last_step=None) is not None


def test_the_provisioning_uri_says_sha1_thirty_seconds_six_digits() -> None:
    uri = totp.provisioning_uri("JBSWY3DPEHPK3PXP", "awa@exemple.com")
    parsed = urllib.parse.urlsplit(uri)
    assert parsed.scheme == "otpauth" and parsed.netloc == "totp"
    assert urllib.parse.unquote(parsed.path) == "/CoGes Administration:awa@exemple.com"
    query = dict(urllib.parse.parse_qsl(parsed.query))
    assert query == {
        "secret": "JBSWY3DPEHPK3PXP",
        "issuer": "CoGes Administration",
        "algorithm": "SHA1",
        "digits": "6",
        "period": "30",
    }
