"""Nettoyage des événements Sentry (ADR 0042) : aucun secret, aucune donnée personnelle."""

from __future__ import annotations

from app.core.logging import request_id_var
from app.core.observability import init_sentry, scrub_event


def test_scrub_removes_credentials_and_personal_data() -> None:
    token = request_id_var.set("req-123")
    try:
        event = scrub_event(
            {
                "request": {
                    "headers": {
                        "Authorization": "Bearer secret",
                        "Cookie": "refresh=abc",
                        "Idempotency-Key": "k",
                        "User-Agent": "navigateur",
                    },
                    "cookies": {"refresh": "abc"},
                    "data": {"password": "x"},
                    "env": {"REMOTE_ADDR": "1.2.3.4"},
                },
                "user": {"id": "u1", "email": "gerant@example.com", "ip_address": "1.2.3.4"},
            }
        )
    finally:
        request_id_var.reset(token)

    assert event["request"]["headers"] == {"User-Agent": "navigateur"}
    assert "cookies" not in event["request"]
    assert "data" not in event["request"]
    assert event["request"]["env"] == {}
    assert event["user"] == {"id": "u1"}
    assert event["tags"]["request_id"] == "req-123"


def test_sentry_stays_off_without_dsn() -> None:
    assert init_sentry("test") is False
