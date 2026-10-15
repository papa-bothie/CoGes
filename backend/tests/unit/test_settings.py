"""Lecture de la configuration depuis l'environnement."""

from __future__ import annotations


def test_settings_strip_a_pasted_trailing_newline(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import Settings

    monkeypatch.setenv("COGES_DATABASE_URL_OWNER", "postgresql+psycopg://coges_owner:x@h/coges\n")
    assert Settings().database_url_owner == "postgresql+psycopg://coges_owner:x@h/coges"


def test_relay_starts_without_the_app_dsn(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Le relais ne reçoit que `COGES_DATABASE_URL_RELAY` (ADR 0032) : la configuration se
    charge, et seul un accès au DSN applicatif échoue, avec un message lisible."""
    import pytest

    from app.core.config import Settings

    monkeypatch.delenv("COGES_DATABASE_URL_APP", raising=False)
    monkeypatch.setenv("COGES_DATABASE_URL_RELAY", "postgresql+psycopg://coges_relay:x@h/coges")
    settings = Settings(_env_file=None)
    assert settings.require_relay_url().startswith("postgresql+psycopg://coges_relay")
    with pytest.raises(RuntimeError, match="COGES_DATABASE_URL_APP est absent"):
        settings.require_app_url()


def test_job_ping_urls_accept_json_or_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`COGES_JOB_PING_URLS` vide ou absent : aucun ping ; une URL non HTTP est refusée."""
    import pytest
    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv("COGES_JOB_PING_URLS", "")
    assert Settings(_env_file=None).job_ping_urls == {}
    monkeypatch.setenv("COGES_JOB_PING_URLS", '{"system.beat_tick": "https://hc-ping.com/x"}')
    assert Settings(_env_file=None).job_ping_urls == {"system.beat_tick": "https://hc-ping.com/x"}
    monkeypatch.setenv("COGES_JOB_PING_URLS", '{"system.beat_tick": "file:///etc/passwd"}')
    with pytest.raises(ValidationError, match="HTTP"):
        Settings(_env_file=None)
