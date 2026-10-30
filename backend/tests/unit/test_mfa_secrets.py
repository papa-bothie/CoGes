"""Secrets de la double authentification (ADR 0105) : chiffrement lié au compte, clé
exigée hors développement, codes de secours sous HMAC, libellé d'appareil sans version."""

from __future__ import annotations

import base64
import secrets
from collections.abc import Iterator
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core import mfa
from app.core.config import DEVELOPMENT_MFA_KEY, Settings

PRODUCTION = {"env": "production", "jwt_secret": "x" * 40}


def _key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


@pytest.fixture
def settings_with(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    def use(key: str | None) -> None:
        settings = Settings(_env_file=None, mfa_encryption_key=key)  # type: ignore[call-arg]
        monkeypatch.setattr(mfa, "get_settings", lambda: settings)
        mfa.reset_key_cache()

    yield use
    mfa.reset_key_cache()


def test_the_secret_round_trips_and_is_not_stored_in_clear(settings_with: object) -> None:
    settings_with(_key())  # type: ignore[operator]
    user = uuid4()
    blob = mfa.encrypt_secret("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP", user)
    assert b"JBSWY3DP" not in blob
    assert mfa.decrypt_secret(blob, user) == "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
    # Nonce aléatoire : deux chiffrements du même secret diffèrent.
    assert mfa.encrypt_secret("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP", user) != blob


def test_a_secret_copied_onto_another_account_does_not_decrypt(settings_with: object) -> None:
    settings_with(_key())  # type: ignore[operator]
    blob = mfa.encrypt_secret("JBSWY3DPEHPK3PXP", uuid4())
    with pytest.raises(mfa.MfaSecretUnreadableError):
        mfa.decrypt_secret(blob, uuid4())


def test_another_key_cannot_read_the_secret(settings_with: object) -> None:
    user = uuid4()
    settings_with(_key())  # type: ignore[operator]
    blob = mfa.encrypt_secret("JBSWY3DPEHPK3PXP", user)
    settings_with(_key())  # type: ignore[operator]
    with pytest.raises(mfa.MfaSecretUnreadableError):
        mfa.decrypt_secret(blob, user)


def test_a_tampered_blob_is_refused(settings_with: object) -> None:
    settings_with(_key())  # type: ignore[operator]
    user = uuid4()
    blob = bytearray(mfa.encrypt_secret("JBSWY3DPEHPK3PXP", user))
    blob[-1] ^= 1
    with pytest.raises(mfa.MfaSecretUnreadableError):
        mfa.decrypt_secret(bytes(blob), user)


def test_the_key_is_required_outside_local_and_ci() -> None:
    settings = Settings(_env_file=None, mfa_encryption_key=None, **PRODUCTION)  # type: ignore[call-arg, arg-type]
    with pytest.raises(RuntimeError, match="COGES_MFA_ENCRYPTION_KEY"):
        settings.require_mfa_encryption_key()
    for env in ("local", "ci"):
        development = Settings(_env_file=None, env=env, mfa_encryption_key=None)  # type: ignore[call-arg, arg-type]
        assert development.require_mfa_encryption_key() == DEVELOPMENT_MFA_KEY


@pytest.mark.parametrize(
    "bad",
    [
        "trop-court",
        base64.urlsafe_b64encode(b"x" * 31).decode(),
        base64.urlsafe_b64encode(b"x" * 33).decode(),
        "!" * 43,
    ],
)
def test_a_key_that_is_not_32_bytes_is_refused_at_start(bad: str) -> None:
    with pytest.raises(ValidationError, match="COGES_MFA_ENCRYPTION_KEY"):
        Settings(_env_file=None, mfa_encryption_key=bad, **PRODUCTION)  # type: ignore[call-arg, arg-type]


def test_a_good_key_is_accepted_with_or_without_padding() -> None:
    raw = secrets.token_bytes(32)
    for value in (
        base64.urlsafe_b64encode(raw).decode(),
        base64.urlsafe_b64encode(raw).decode().rstrip("="),
    ):
        settings = Settings(_env_file=None, mfa_encryption_key=value, **PRODUCTION)  # type: ignore[call-arg, arg-type]
        assert settings.require_mfa_encryption_key() == raw


def test_recovery_codes_are_ten_distinct_unambiguous_codes(settings_with: object) -> None:
    settings_with(_key())  # type: ignore[operator]
    codes = mfa.generate_recovery_codes()
    assert len(codes) == len(set(codes)) == 10
    for code in codes:
        assert mfa.RECOVERY_CODE.fullmatch(code)
        assert not set(code) & set("01ILO")


def test_recovery_digests_are_keyed_and_bound_to_the_account(settings_with: object) -> None:
    settings_with(_key())  # type: ignore[operator]
    user = uuid4()
    normalised = mfa.normalise_recovery_code("abcd-efgh")
    assert normalised == "ABCDEFGH"
    digest = mfa.recovery_code_digest(user, normalised)
    assert len(digest) == 64 and "ABCDEFGH" not in digest
    assert (
        mfa.recovery_code_digest(user, mfa.normalise_recovery_code(" ABCD EFGH ") or "") == digest
    )
    assert mfa.recovery_code_digest(uuid4(), normalised) != digest
    settings_with(_key())  # type: ignore[operator]
    assert mfa.recovery_code_digest(user, normalised) != digest


@pytest.mark.parametrize("typed", ["", "ABC-DEFG", "ABCD-EFG0", "ABCDEFGHI", "1234-5678"])
def test_malformed_recovery_codes_are_rejected_before_any_lookup(typed: str) -> None:
    assert mfa.normalise_recovery_code(typed) is None


@pytest.mark.parametrize(
    ("agent", "label"),
    [
        (
            "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
            "Firefox · Linux",
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0 Safari/537.36 Edg/141.0",
            "Edge · Windows",
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
            "Safari · iPhone",
        ),
        (None, "Navigateur inconnu · système inconnu"),
    ],
)
def test_the_browser_label_has_no_version(agent: str | None, label: str) -> None:
    assert mfa.browser_label(agent) == label


def test_mfa_is_required_by_a_constant_of_the_code() -> None:
    assert mfa.PLATFORM_MFA_REQUIRED is True
