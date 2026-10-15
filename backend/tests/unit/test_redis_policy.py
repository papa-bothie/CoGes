"""Le worker refuse Redis en éviction en production, avertit ailleurs (ADR 0077)."""

from __future__ import annotations

from typing import Any

import pytest

from app.workers import preflight
from app.workers.preflight import RedisEvictionPolicyError, check_redis_eviction_policy


class FakeRedis:
    def __init__(self, policy: str | None) -> None:
        self.policy = policy

    def info(self, section: str) -> dict[str, Any]:
        if self.policy is None:
            raise ConnectionError("down")
        return {"maxmemory_policy": self.policy}


def _check(policy: str | None, env: str) -> str | None:
    return check_redis_eviction_policy(FakeRedis(policy), env)  # type: ignore[arg-type]


def test_noeviction_is_accepted_everywhere() -> None:
    assert _check("noeviction", "production") == "noeviction"


def test_eviction_refused_in_production() -> None:
    with pytest.raises(RedisEvictionPolicyError):
        _check("allkeys-lru", "production")


@pytest.mark.parametrize("env", ["local", "ci", "staging"])
def test_eviction_only_warns_elsewhere(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Le journal du module, et non `caplog` : la configuration JSON du worker, posée par
    # d'autres tests de la suite, coupe la propagation vers la racine.
    warnings: list[str] = []
    monkeypatch.setattr(
        preflight.logger, "warning", lambda message, *a, **k: warnings.append(message)
    )
    assert _check("volatile-lru", env) == "volatile-lru"
    assert len(warnings) == 1
    assert "noeviction" in warnings[0]


def test_unreadable_policy_does_not_block() -> None:
    assert _check(None, "production") is None
