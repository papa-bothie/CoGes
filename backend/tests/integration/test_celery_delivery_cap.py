"""Tâches Celery : plafond de redélivrance, nouvel essai des alertes, arrêt propre (P2.14).

* `acks_late` + `reject_on_worker_lost` : une tâche qui fait tomber le worker (mémoire,
  segfault) est rendue à la file… et le refait tomber, sans fin. Au-delà de
  `MAX_DELIVERIES` livraisons interrompues, elle est écartée et signalée.
* Les alertes (stock, annulation, échecs de connexion) échouaient pour de bon à la
  première erreur de base, quand l'analytique retentait trois fois.
* Les conteneurs laissaient 10 s (défaut de Docker) à des tâches qui en durent jusqu'à
  360 : un redéploiement coupait des tâches en plein travail.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.core import cache
from app.workers import celery_app as celery_module
from app.workers.celery_app import celery_app
from app.workers.tasks import notifications

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
RUNS: list[str] = []


@celery_app.task(name="tests.crashy")
def crashy() -> str:
    RUNS.append("run")
    return "done"


@pytest.fixture
def redis_client() -> Any:
    client = cache.get_client()
    if client is None:
        pytest.skip("Redis requis")
    return client


def test_a_task_that_keeps_killing_the_worker_is_set_aside(redis_client: Any) -> None:
    task_id = uuid4().hex
    cap = getattr(celery_module, "MAX_DELIVERIES", 3)
    # Trois livraisons déjà commencées, jamais terminées : trois workers tombés.
    redis_client.set(f"coges:celery:deliveries:{task_id}", cap, ex=3600)
    RUNS.clear()

    crashy.apply(task_id=task_id)

    assert RUNS == [], "la tâche qui fait tomber le worker est relancée sans fin"


def test_a_normal_task_runs_and_leaves_no_counter(redis_client: Any) -> None:
    task_id = uuid4().hex
    RUNS.clear()

    crashy.apply(task_id=task_id)

    assert RUNS == ["run"]
    assert redis_client.get(f"coges:celery:deliveries:{task_id}") is None


def _message() -> dict[str, Any]:
    from datetime import UTC, datetime  # noqa: PLC0415

    from app.core.events.inbox import Event  # noqa: PLC0415
    from app.core.events.types import EventType  # noqa: PLC0415

    return Event(
        id=930_000_000 + uuid4().int % 1_000_000,
        company_id=uuid4(),
        event_type=EventType.STOCK_UPDATED,
        aggregate_type="product",
        aggregate_id=uuid4(),
        payload={"qty_on_hand": "0", "below_reorder_point": True, "product_id": str(uuid4())},
        occurred_at=datetime.now(UTC),
    ).as_message()


@pytest.mark.parametrize(
    ("task", "arguments"),
    [
        ("on_stock_updated", None),
        ("on_sale_cancelled", None),
        ("login_failures", {"company_id": str(uuid4()), "user_id": str(uuid4()), "failures": 10}),
    ],
)
def test_alert_tasks_retry_on_a_database_error(
    monkeypatch: pytest.MonkeyPatch, task: str, arguments: dict[str, Any] | None
) -> None:
    attempts: list[int] = []

    def broken(*args: Any, **kwargs: Any) -> Any:
        attempts.append(1)
        raise ConnectionError("base injoignable (test)")

    monkeypatch.setattr(notifications, "handle", broken)
    monkeypatch.setattr(notifications, "tenant_transaction", broken)

    # Exécutée sur place, la tâche enchaîne ses nouveaux essais avant d'échouer.
    getattr(notifications, task).apply(kwargs=arguments or _message())

    assert len(attempts) == 4, f"{task} : {len(attempts)} essai(s), aucun nouvel essai"


@pytest.mark.parametrize(
    "compose", ["deploy/vps/docker-compose.yml", "deploy/docker-compose.worker.yml"]
)
def test_containers_give_long_tasks_time_to_finish(compose: str) -> None:
    text = (REPO / compose).read_text(encoding="utf-8")
    for service in ("worker", "beat", "relay"):
        block = re.search(rf"\n  {service}:\n(.*?)(?=\n  [a-z-]+:\n|\Z)", text, re.S)
        assert block is not None, f"{service} absent de {compose}"
        assert "stop_grace_period: 120s" in block.group(1), f"{service} : arrêt en 10 s"
