"""`GET /api/v1/health/ready` : l'API, PostgreSQL et Redis (ADR 0081)."""

from __future__ import annotations

from typing import Any

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

pytestmark = pytest.mark.integration

URL = "/api/v1/health/ready"


@pytest.fixture
def ready_database(monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Any]) -> None:
    """La sonde interroge `coges_test` sous `coges_app`, comme une requête métier."""
    monkeypatch.setattr("app.core.readiness.get_session_factory", lambda: session_factory)


@pytest.fixture
def ready_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis local réellement joignable, et réputé configuré."""
    client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1)
    try:
        client.ping()
    except redis.RedisError:
        pytest.skip("Redis local injoignable")
    finally:
        client.close()
    monkeypatch.setattr("app.core.readiness.redis_configured", lambda: True)


def _unreachable_redis() -> redis.Redis:
    return redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2, socket_timeout=0.2)


def _broken_factory() -> Any:
    def open_session() -> Any:
        raise OSError("connexion refusée")

    return open_session


def test_ready_when_database_and_redis_answer(
    client: TestClient, ready_database: None, ready_redis: None
) -> None:
    response = client.get(URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def test_unavailable_when_the_database_is_down(
    client: TestClient, ready_redis: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.core.readiness.get_session_factory", _broken_factory)

    response = client.get(URL)

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "down", "redis": "ok"},
    }
    assert "refusée" not in response.text


def test_unavailable_when_a_configured_redis_is_down(
    client: TestClient, ready_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.core.readiness.redis_configured", lambda: True)
    monkeypatch.setattr("app.core.heartbeat.redis_client", _unreachable_redis)

    response = client.get(URL)

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "down"}


def test_ready_without_redis_configured(
    client: TestClient, ready_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.core.readiness.redis_configured", lambda: False)
    monkeypatch.setattr("app.core.heartbeat.redis_client", _unreachable_redis)

    response = client.get(URL)

    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "redis": "not_configured"}


def test_redis_counts_as_configured_only_when_its_address_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import readiness
    from app.core.config import Settings

    monkeypatch.delenv("COGES_REDIS_URL", raising=False)
    monkeypatch.setattr(readiness, "get_settings", lambda: Settings(_env_file=None))
    assert readiness.redis_configured() is False

    monkeypatch.setenv("COGES_REDIS_URL", "redis://cache.example:6379/0")
    assert readiness.redis_configured() is True
