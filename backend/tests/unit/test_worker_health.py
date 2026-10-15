"""Battements de cœur et sonde de santé des conteneurs de la zone B (ADR 0077)."""

from __future__ import annotations

import time

import pytest
import redis

from app.core import heartbeat
from app.workers import health

HOST = "test-host"


def _check(client: redis.Redis, component: str, **kwargs: object) -> tuple[bool, str]:
    return health.check(component, host=HOST, client_factory=lambda: client, **kwargs)  # type: ignore[arg-type]


def test_missing_heartbeat_exits_1(ops_redis: redis.Redis) -> None:
    """Aucun battement : la sonde échoue, et le conteneur finira relancé."""
    healthy, reason = _check(ops_redis, "relay")
    assert healthy is False
    assert reason == "aucun battement"


def test_stale_heartbeat_exits_1(ops_redis: redis.Redis) -> None:
    """Un battement de plus de 90 s vaut une absence, même avant l'expiration de la clé."""
    heartbeat.beat(ops_redis, "beat", HOST, now=time.time() - 95)
    healthy, _ = _check(ops_redis, "beat")
    assert healthy is False


def test_fresh_heartbeat_exits_0(ops_redis: redis.Redis) -> None:
    heartbeat.beat(ops_redis, "relay", HOST)
    assert _check(ops_redis, "relay")[0] is True
    assert ops_redis.ttl(heartbeat.heartbeat_key("relay", HOST)) <= heartbeat.TTL_SECONDS


def test_worker_also_needs_to_answer_the_ping(ops_redis: redis.Redis) -> None:
    """Le worker qui bat sans répondre à `inspect ping` est malade."""
    heartbeat.beat(ops_redis, "worker", HOST)
    assert _check(ops_redis, "worker", celery_ping=lambda host: True)[0] is True
    healthy, reason = _check(ops_redis, "worker", celery_ping=lambda host: False)
    assert healthy is False
    assert "ping" in reason


def test_heartbeat_of_another_host_does_not_count(ops_redis: redis.Redis) -> None:
    """La sonde d'un conteneur ne lit que son propre battement."""
    heartbeat.beat(ops_redis, "beat", "other-host")
    assert _check(ops_redis, "beat")[0] is False


def test_unreachable_redis_exits_1() -> None:
    def broken() -> redis.Redis:
        raise redis.ConnectionError("down")

    healthy, reason = health.check("relay", host=HOST, client_factory=broken)
    assert healthy is False
    assert "Redis" in reason


def test_main_exit_codes(ops_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m app.workers.health relay` : 1 sans battement, 0 avec."""
    monkeypatch.setattr(heartbeat, "hostname", lambda: HOST)
    assert health.main(["relay"]) == 1
    heartbeat.beat(ops_redis, "relay", HOST)
    assert health.main(["relay"]) == 0
    assert health.main([]) == 2


def test_heartbeat_thread_survives_redis_outage() -> None:
    """Une panne de Redis est journalisée, jamais levée : le processus continue."""

    class Broken:
        def set(self, *args: object, **kwargs: object) -> None:
            raise redis.ConnectionError("down")

    beat = heartbeat.Heartbeat("worker", client=Broken(), host=HOST)  # type: ignore[arg-type]
    assert beat.beat_once() is False


def test_read_pulses_lists_every_component(ops_redis: redis.Redis) -> None:
    now = time.time()
    heartbeat.beat(ops_redis, "worker", "a", now=now - 10)
    heartbeat.beat(ops_redis, "relay", "b", now=now - 100)
    pulses = heartbeat.read_pulses(ops_redis, now=now)
    assert [(p.component, p.host, p.fresh) for p in pulses] == [
        ("relay", "b", False),
        ("worker", "a", True),
    ]
