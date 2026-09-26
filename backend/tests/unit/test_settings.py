"""Lecture de la configuration depuis l'environnement."""

from __future__ import annotations


def test_settings_strip_a_pasted_trailing_newline(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import Settings

    monkeypatch.setenv("COGES_DATABASE_URL_OWNER", "postgresql+psycopg://coges_owner:x@h/coges\n")
    assert Settings().database_url_owner == "postgresql+psycopg://coges_owner:x@h/coges"
