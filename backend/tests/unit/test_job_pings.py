"""Pings « homme mort » (ADR 0077) : succès, `/fail`, `{status}`, jamais bloquants."""

from __future__ import annotations

import pytest

from app.workers import pings

URL = "https://hc-ping.com/abc"


def test_success_pings_the_url_and_failure_appends_fail() -> None:
    called: list[str] = []
    assert pings.ping("job", ok=True, urls={"job": URL}, opener=called.append) is True
    assert pings.ping("job", ok=False, urls={"job": URL + "/"}, opener=called.append) is True
    assert called == [URL, URL + "/fail"]


def test_status_placeholder_for_sentry_crons() -> None:
    url = "https://o1.ingest.sentry.io/api/2/cron/rebuild/key/?status={status}"
    assert pings.ping_target(url, ok=True).endswith("?status=ok")
    assert pings.ping_target(url, ok=False).endswith("?status=error")


def test_absent_variable_means_no_ping() -> None:
    called: list[str] = []
    assert pings.ping("job", ok=True, urls={}, opener=called.append) is False
    assert called == []


def test_timeout_is_swallowed() -> None:
    """Un service de surveillance en panne ne fait jamais échouer une tâche."""

    def slow(url: str) -> None:
        raise TimeoutError("trop lent")

    assert pings.ping("job", ok=True, urls={"job": URL}, opener=slow) is False


def test_real_request_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le vrai appel part avec un délai de 5 s, sans corps."""
    seen: dict[str, object] = {}

    def fake_urlopen(request: object, timeout: float) -> object:
        seen["timeout"] = timeout
        seen["method"] = request.get_method()  # type: ignore[attr-defined]
        seen["data"] = request.data  # type: ignore[attr-defined]
        raise TimeoutError("lent")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert pings.ping("job", ok=True, urls={"job": URL}) is False
    assert seen == {"timeout": pings.TIMEOUT_SECONDS, "method": "GET", "data": None}
