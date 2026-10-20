"""E-mails de l'administration (ADR 0089), côté worker."""

from __future__ import annotations

from typing import Any

import pytest

from app.core import mailer
from app.core.config import get_settings
from app.workers.tasks import platform as platform_tasks
from tests.conftest import DemoCompany


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def _send(**message: Any) -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(mailer, "send_email", _send)
    return sent


def test_the_manager_is_told_of_a_suspension(
    workers_bound_to_test_database: None,
    company_alpha: DemoCompany,
    outbox: list[dict[str, Any]],
) -> None:
    assert platform_tasks.company_status_changed.run(str(company_alpha.company_id), "suspended")
    [message] = outbox
    assert company_alpha.email in message["to"]
    assert "suspendu" in message["subject"]
    assert "Societe Alpha" in message["body"]


def test_an_unknown_status_sends_nothing(
    workers_bound_to_test_database: None,
    company_alpha: DemoCompany,
    outbox: list[dict[str, Any]],
) -> None:
    assert (
        platform_tasks.company_status_changed.run(str(company_alpha.company_id), "trial") is False
    )
    assert outbox == []


def test_repeated_platform_login_failures_reach_the_team(
    monkeypatch: pytest.MonkeyPatch, outbox: list[dict[str, Any]]
) -> None:
    patched = get_settings().model_copy(update={"platform_alert_email": "equipe@example.com"})
    monkeypatch.setattr(platform_tasks, "get_settings", lambda: patched)
    assert platform_tasks.login_failures.run("00000000-0000-0000-0000-000000000001", 10)
    assert outbox[0]["to"] == ["equipe@example.com"]


def test_without_a_team_address_nothing_is_sent(
    monkeypatch: pytest.MonkeyPatch, outbox: list[dict[str, Any]]
) -> None:
    patched = get_settings().model_copy(update={"platform_alert_email": None})
    monkeypatch.setattr(platform_tasks, "get_settings", lambda: patched)
    assert platform_tasks.login_failures.run("00000000-0000-0000-0000-000000000001", 10) is False
    assert outbox == []
