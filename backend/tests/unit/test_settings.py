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


def test_cloudflare_access_settings_go_together(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """ADR 0104 : domaine d'équipe et AUD posés ensemble, bien formés ; vides = absents ;
    l'adresse des clés de test refusée hors `local` et `ci`."""
    import pytest
    from pydantic import ValidationError

    from app.core.config import Settings

    team, aud = "coges.cloudflareaccess.com", "a" * 64
    monkeypatch.setenv("COGES_ACCESS_TEAM_DOMAIN", "")
    monkeypatch.setenv("COGES_ACCESS_AUD", "")
    assert Settings(_env_file=None).access_team_domain is None

    monkeypatch.setenv("COGES_ACCESS_TEAM_DOMAIN", team)
    with pytest.raises(ValidationError, match="vont ensemble"):
        Settings(_env_file=None)

    monkeypatch.setenv("COGES_ACCESS_AUD", aud)
    assert Settings(_env_file=None).access_aud == aud

    for bad_team in ("https://coges.cloudflareaccess.com", "coges.example.com"):
        monkeypatch.setenv("COGES_ACCESS_TEAM_DOMAIN", bad_team)
        with pytest.raises(ValidationError, match="nom d'hôte nu"):
            Settings(_env_file=None)
    monkeypatch.setenv("COGES_ACCESS_TEAM_DOMAIN", team)

    monkeypatch.setenv("COGES_ACCESS_AUD", "pas-une-aud")
    with pytest.raises(ValidationError, match="64 caractères"):
        Settings(_env_file=None)
    monkeypatch.setenv("COGES_ACCESS_AUD", aud)

    monkeypatch.setenv("COGES_ACCESS_CERTS_URL", "http://127.0.0.1:8199/cdn-cgi/access/certs")
    monkeypatch.setenv("COGES_ENV", "ci")
    assert Settings(_env_file=None).access_certs_url
    monkeypatch.setenv("COGES_ENV", "production")
    monkeypatch.setenv("COGES_JWT_SECRET", "x" * 40)
    with pytest.raises(ValidationError, match="COGES_ACCESS_CERTS_URL"):
        Settings(_env_file=None)
