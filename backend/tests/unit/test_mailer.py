"""Envoi d'e-mails (ADR 0089) : rien ne part sans SMTP configuré, et rien n'échoue."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from app.core import mailer
from app.core.config import get_settings


class _FakeSMTP:
    sent: list[Any] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.calls: list[str] = [f"connect {host}:{port}"]

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self, context: Any) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login {user}")

    def send_message(self, message: Any) -> None:
        _FakeSMTP.sent.append((self.calls, message))


def _settings(monkeypatch: pytest.MonkeyPatch, **update: Any) -> None:
    patched = get_settings().model_copy(update=update)
    monkeypatch.setattr(mailer, "get_settings", lambda: patched)


def test_nothing_is_sent_without_a_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, smtp_host=None)
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.sent = []
    assert mailer.send_email(to=["gerant@example.com"], subject="s", body="b") is False
    assert _FakeSMTP.sent == []


def test_nobody_to_write_to_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, smtp_host="smtp.example.com")
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.sent = []
    assert mailer.send_email(to=[], subject="s", body="b") is False
    assert _FakeSMTP.sent == []


def test_a_configured_host_sends_over_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(
        monkeypatch,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="equipe",
        smtp_password=SecretStr("secret"),
        smtp_from="CoGes <equipe@example.com>",
    )
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.sent = []
    assert mailer.send_email(to=["gerant@example.com"], subject="Objet", body="Corps") is True
    [(calls, message)] = _FakeSMTP.sent
    assert calls == ["connect smtp.example.com:587", "starttls", "login equipe"]
    assert message["To"] == "gerant@example.com"
    assert message["Subject"] == "Objet"
    assert message["From"] == "CoGes <equipe@example.com>"
