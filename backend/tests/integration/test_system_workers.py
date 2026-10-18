"""`GET /api/v1/system/workers` — le bilan de la zone B (ADR 0077).

Trois causes de 503 sont exigées : un battement absent, une outbox en retard, une
tâche de nuit qui n'a pas réussi. Plus les variantes : tâche jamais lancée, trop
ancienne, entreprise en échec, tic de beat muet.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core import heartbeat
from app.core.tenancy import TenantContext, tenant_transaction
from app.workers.beat import JOB_FRESHNESS, ML_TRAIN, REBUILD_STOCK
from tests.conftest import DemoCompany, login_token
from tests.integration.ops_harness import OPS_TOKEN, add_run, clear_job_runs, ops_settings
from tests.integration.relay_harness import bury_dead_letters
from tests.tenancy.harness import Tenant

URL = "/api/v1/system/workers"
AUTH = {"Authorization": f"Bearer {OPS_TOKEN}"}
HOST = "conteneur-de-test"
#: Le jeu de test garde des événements jamais publiés par d'autres suites : le seuil
#: est relevé, sauf dans le test qui le vise.
GENEROUS_LAG = 10 * 365 * 86400


def _use_settings(monkeypatch: pytest.MonkeyPatch, **update: Any) -> None:
    settings = ops_settings(**update)
    monkeypatch.setattr("app.core.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.modules.system.service.get_settings", lambda: settings)


@pytest.fixture
def healthy(
    api_client: TestClient,
    ops_redis: redis.Redis,
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Tout va bien : trois battements, un tic récent, chaque tâche réussie il y a 1 h."""
    _use_settings(monkeypatch, ops_outbox_max_lag_seconds=GENEROUS_LAG)
    for component in heartbeat.COMPONENTS:
        heartbeat.beat(ops_redis, component, HOST)
    heartbeat.record_beat_tick(ops_redis)
    clear_job_runs(owner_engine)
    for job in JOB_FRESHNESS:
        add_run(owner_engine, job)
    bury_dead_letters(owner_engine)
    yield api_client
    clear_job_runs(owner_engine)


def test_everything_healthy_is_200(healthy: TestClient) -> None:
    response = healthy.get(URL, headers=AUTH)
    assert response.status_code == 200, response.json()["problems"]
    body = response.json()
    assert body["healthy"] is True
    assert body["problems"] == []
    assert {c["component"] for c in body["components"] if c["healthy"]} == {
        "worker",
        "beat",
        "relay",
    }
    assert body["queue"]["name"] == "celery"


def test_missing_heartbeat_is_503(healthy: TestClient, ops_redis: redis.Redis) -> None:
    ops_redis.delete(heartbeat.heartbeat_key("relay", HOST))
    response = healthy.get(URL, headers=AUTH)
    assert response.status_code == 503
    assert response.json()["problems"] == ["heartbeat_missing:relay"]


def test_stale_heartbeat_is_503(healthy: TestClient, ops_redis: redis.Redis) -> None:
    heartbeat.beat(ops_redis, "beat", HOST, now=time.time() - 100)
    response = healthy.get(URL, headers=AUTH)
    assert response.status_code == 503
    assert "heartbeat_missing:beat" in response.json()["problems"]


def test_silent_beat_tick_is_503(healthy: TestClient, ops_redis: redis.Redis) -> None:
    heartbeat.record_beat_tick(ops_redis, now=time.time() - 20 * 60)
    response = healthy.get(URL, headers=AUTH)
    assert response.status_code == 503
    assert response.json()["problems"] == ["beat_tick_missing"]


def test_lagging_outbox_is_503(
    healthy: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Any],
    owner_engine: Engine,
    tenant_a: Tenant,
) -> None:
    """Un événement en attente depuis 2 h, pour un seuil de 1 h."""
    _use_settings(monkeypatch, ops_outbox_max_lag_seconds=3600)
    with tenant_transaction(
        TenantContext.bootstrap(tenant_a.company_id), session_factory=session_factory
    ) as session:
        event_id = session.execute(
            text(
                """
                INSERT INTO business_events
                       (company_id, event_type, aggregate_type, aggregate_id, payload, occurred_at)
                VALUES (:company_id, 'stock.updated', 'product', gen_random_uuid(), '{}'::jsonb,
                        now() - interval '2 hours')
                RETURNING id
                """
            ),
            {"company_id": tenant_a.company_id},
        ).scalar_one()
    try:
        response = healthy.get(URL, headers=AUTH)
        assert response.status_code == 503
        body = response.json()
        assert body["problems"] == ["outbox_lagging"]
        assert body["outbox"]["lag_seconds"] >= 7200
        assert body["outbox"]["pending"] >= 1
    finally:
        # L'événement est marqué publié pour ne pas fausser les autres suites.
        with owner_engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE coges_bus"))
            connection.execute(
                text("UPDATE business_events SET published_at = now() WHERE id = :id"),
                {"id": event_id},
            )


def test_dead_lettered_event_is_503(
    healthy: TestClient,
    session_factory: sessionmaker[Any],
    owner_engine: Engine,
    tenant_a: Tenant,
) -> None:
    """Un événement au rebut ne repart jamais seul : le bilan le dit, avec le compte."""
    with tenant_transaction(
        TenantContext.bootstrap(tenant_a.company_id), session_factory=session_factory
    ) as session:
        session.execute(
            text(
                """
                INSERT INTO business_events
                       (company_id, event_type, aggregate_type, aggregate_id, payload)
                VALUES (:company_id, 'stock.updated', 'product', gen_random_uuid(), '{}'::jsonb)
                """
            ),
            {"company_id": tenant_a.company_id},
        )
    with owner_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE coges_bus"))
        connection.execute(
            text(
                "UPDATE business_events SET attempts = 10 "
                "WHERE company_id = :company_id AND published_at IS NULL"
            ),
            {"company_id": tenant_a.company_id},
        )
    try:
        response = healthy.get(URL, headers=AUTH)
        assert response.status_code == 503
        body = response.json()
        assert body["problems"] == [f"outbox_dead_lettered:{body['outbox']['dead_lettered']}"]
        assert body["outbox"]["dead_lettered"] >= 1
    finally:
        bury_dead_letters(owner_engine)


def test_failed_nightly_job_is_503(healthy: TestClient, owner_engine: Engine) -> None:
    add_run(owner_engine, REBUILD_STOCK, status="failed", hours_ago=0.5)
    response = healthy.get(URL, headers=AUTH)
    assert response.status_code == 503
    assert response.json()["problems"] == [f"job_failed:{REBUILD_STOCK}"]


def test_job_without_success_for_26_hours_is_503(healthy: TestClient, owner_engine: Engine) -> None:
    clear_job_runs(owner_engine)
    for job in JOB_FRESHNESS:
        add_run(owner_engine, job, hours_ago=27 if job == REBUILD_STOCK else 1)
    response = healthy.get(URL, headers=AUTH)
    assert response.status_code == 503
    assert response.json()["problems"] == [f"job_stale:{REBUILD_STOCK}"]


def test_weekly_job_has_eight_days(healthy: TestClient, owner_engine: Engine) -> None:
    """L'entraînement du lundi n'est pas en retard le samedi."""
    clear_job_runs(owner_engine)
    for job in JOB_FRESHNESS:
        add_run(owner_engine, job, hours_ago=6 * 24 if job == ML_TRAIN else 1)
    assert healthy.get(URL, headers=AUTH).status_code == 200


def test_job_that_never_ran_is_503(healthy: TestClient, owner_engine: Engine) -> None:
    clear_job_runs(owner_engine)
    response = healthy.get(URL, headers=AUTH)
    assert response.status_code == 503
    assert f"job_never_ran:{REBUILD_STOCK}" in response.json()["problems"]


def test_running_trace_older_than_the_time_limit_counts_as_failed(
    healthy: TestClient, owner_engine: Engine
) -> None:
    """Un worker tué en pleine tâche laisse `running` : passé 6 min, c'est un échec."""
    add_run(owner_engine, REBUILD_STOCK, status="running", hours_ago=0.2)
    response = healthy.get(URL, headers=AUTH)
    assert response.json()["problems"] == [f"job_failed:{REBUILD_STOCK}"]


def test_company_failure_is_503_without_naming_the_company(
    healthy: TestClient, owner_engine: Engine, tenant_a: Tenant
) -> None:
    """Une entreprise en échec : compté, jamais nommé ni identifié."""
    subtask = JOB_FRESHNESS[REBUILD_STOCK].per_company
    assert subtask is not None
    add_run(owner_engine, subtask, status="failed", company_id=tenant_a.company_id)
    response = healthy.get(URL, headers=AUTH)
    assert response.status_code == 503
    assert response.json()["problems"] == [f"job_companies_failed:{REBUILD_STOCK}"]
    [job] = [j for j in response.json()["jobs"] if j["job"] == REBUILD_STOCK]
    assert job["companies_failed"] == 1
    assert str(tenant_a.company_id) not in response.text
    assert tenant_a.slug.upper() not in response.text.upper()


def test_without_token_is_401(healthy: TestClient) -> None:
    response = healthy.get(URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_wrong_token_is_401(healthy: TestClient) -> None:
    response = healthy.get(URL, headers={"Authorization": "Bearer pas-le-bon"})
    assert response.status_code == 401


def test_user_access_token_is_not_an_ops_token(
    healthy: TestClient, company_alpha: DemoCompany
) -> None:
    """Un jeton de gérant n'ouvre pas le bilan de plate-forme."""
    token = login_token(healthy, company_alpha)
    response = healthy.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_unconfigured_token_hides_the_route(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_settings(monkeypatch, ops_token=None)
    response = api_client.get(URL, headers=AUTH)
    assert response.status_code == 404
