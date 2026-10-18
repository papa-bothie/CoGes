"""L'heure métier, figée ou non (ADR 0065)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core import clock
from app.core.config import Settings, get_settings

FROZEN = "2026-10-06T10:45:00+00:00"


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("COGES_FROZEN_NOW", FROZEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_without_frozen_time_the_clock_is_real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COGES_FROZEN_NOW", raising=False)
    get_settings.cache_clear()
    try:
        assert abs(clock.now() - datetime.now(UTC)) < timedelta(seconds=5)
    finally:
        get_settings.cache_clear()


def test_frozen_time_is_the_business_now(frozen: None) -> None:
    assert clock.now() == datetime(2026, 10, 6, 10, 45, tzinfo=UTC)
    assert clock.today_in("Africa/Dakar") == date(2026, 10, 6)
    # Le jour dépend du fuseau de l'entreprise : à Tokyo, il est déjà 19 h 45 le 6.
    assert clock.now_in("Asia/Tokyo").hour == 19
    assert clock.today_utc() == date(2026, 10, 6)


def test_frozen_time_needs_a_time_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COGES_FROZEN_NOW", "2026-10-06T10:45:00")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_frozen_time_is_refused_outside_local_and_ci(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("COGES_FROZEN_NOW", FROZEN)
    monkeypatch.setenv("COGES_ENV", env)
    # Un vrai secret : hors `local` et `ci`, celui du modèle est refusé lui aussi (ADR 0087).
    monkeypatch.setenv("COGES_JWT_SECRET", "secret-de-test-tire-au-hasard-" + "x" * 32)
    with pytest.raises(
        ValidationError, match="COGES_FROZEN_NOW n'est accepté qu'en local et en CI"
    ):
        Settings(_env_file=None)


@pytest.mark.parametrize("env", ["local", "ci"])
def test_frozen_time_is_accepted_in_local_and_ci(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("COGES_FROZEN_NOW", FROZEN)
    monkeypatch.setenv("COGES_ENV", env)
    assert Settings(_env_file=None).frozen_now is not None
