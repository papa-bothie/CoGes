"""Redis absent au démarrage, présent ensuite : le cache revient (P2.2, ADR 0088).

`get_client` était sous `lru_cache` : un premier échec restait mémorisé, et le cache,
les limites par IP et par entreprise restaient coupés jusqu'au redémarrage du processus.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.core import cache


class _FakeRedis:
    def __init__(self, *, up: bool) -> None:
        self.up = up

    def ping(self) -> bool:
        if not self.up:
            raise ConnectionError("Connection refused")
        return True


@pytest.fixture
def redis_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    state: dict[str, Any] = {"up": False, "attempts": 0, "now": 1000.0}

    def from_url(*args: Any, **kwargs: Any) -> _FakeRedis:
        state["attempts"] += 1
        return _FakeRedis(up=state["up"])

    monkeypatch.setattr(cache.redis.Redis, "from_url", from_url)
    monkeypatch.setattr(cache, "_monotonic", lambda: state["now"])
    cache.reset_client()
    yield state
    cache.reset_client()


def test_a_failure_at_startup_is_not_remembered_forever(redis_state: dict[str, Any]) -> None:
    assert cache.get_client() is None

    redis_state["up"] = True
    redis_state["now"] += 10

    assert cache.get_client() is not None, "Redis revenu, le processus ne le voit pas"


def test_a_failure_is_not_retried_on_every_call(redis_state: dict[str, Any]) -> None:
    """Pendant la panne, pas une connexion par requête : un essai toutes les quelques s."""
    assert cache.get_client() is None
    attempts = redis_state["attempts"]

    for _ in range(50):
        assert cache.get_client() is None

    assert redis_state["attempts"] == attempts


def test_a_working_client_is_kept(redis_state: dict[str, Any]) -> None:
    redis_state["up"] = True
    first = cache.get_client()
    assert first is not None
    assert cache.get_client() is first
