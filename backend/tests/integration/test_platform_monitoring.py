"""Historique des tâches et rebut de l'outbox pour l'administration (ADR 0090).

`GET /api/v1/platform/system/job-runs` et `GET /api/v1/platform/system/outbox` : lus
sous `coges_app_platform`, par deux fonctions `SECURITY DEFINER` qui ne rendent ni
`company_id`, ni nom d'entreprise, ni contenu d'événement. Le dernier test balaie le
JSON à la recherche de ce qui ne doit jamais y être, comme au lot C.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import TenantContext, tenant_transaction
from app.workers.beat import JOB_FRESHNESS, PURGE_JOB_RUNS, REBUILD_STOCK
from tests.conftest import DemoCompany, auth_headers, login_token
from tests.integration.ops_harness import OPS_TOKEN, add_run, clear_job_runs
from tests.integration.platform_harness import create_platform_account, platform_login
from tests.integration.relay_harness import bury_dead_letters
from tests.tenancy.harness import Tenant

JOB_RUNS = "/api/v1/platform/system/job-runs"
OUTBOX = "/api/v1/platform/system/outbox"

RUN_KEYS = {"id", "job", "status", "started_at", "finished_at", "error", "per_company"}
DEAD_LETTER_KEYS = {"id", "event_type", "occurred_at", "attempts"}

#: Ce que le contenu d'un événement au rebut porte, et qui ne doit jamais sortir.
PAYLOAD_CUSTOMER = "Aminata Cliente-Secrète"
PAYLOAD_AMOUNT = "987654.32"


@pytest.fixture
def client(api_client: TestClient, platform_bound_to_test_database: None) -> TestClient:
    return api_client


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return auth_headers(platform_login(client, create_platform_account("support")))


@pytest.fixture
def runs(owner_engine: Engine, tenant_a: Tenant) -> Iterator[None]:
    """Cinq exécutions récentes, dont deux échecs, et une trop vieille pour sortir."""
    clear_job_runs(owner_engine)
    subtask = JOB_FRESHNESS[REBUILD_STOCK].per_company
    assert subtask is not None
    add_run(owner_engine, REBUILD_STOCK, hours_ago=5)
    add_run(owner_engine, REBUILD_STOCK, status="failed", hours_ago=4, error="OperationalError")
    add_run(owner_engine, subtask, company_id=tenant_a.company_id, hours_ago=3)
    # Un worker tué : `running` depuis 12 min, donc un échec pour la lecture.
    add_run(owner_engine, REBUILD_STOCK, status="running", hours_ago=0.2)
    add_run(owner_engine, PURGE_JOB_RUNS, hours_ago=0.1)
    add_run(owner_engine, REBUILD_STOCK, hours_ago=91 * 24)
    yield
    clear_job_runs(owner_engine)


@pytest.fixture
def dead_letter(
    session_factory: sessionmaker[Any], owner_engine: Engine, tenant_a: Tenant
) -> Iterator[int]:
    """Un événement au rebut dont le contenu cite un client et un montant."""
    with tenant_transaction(
        TenantContext.bootstrap(tenant_a.company_id), session_factory=session_factory
    ) as session:
        event_id = session.execute(
            text(
                """
                INSERT INTO business_events
                       (company_id, event_type, aggregate_type, aggregate_id, payload)
                VALUES (:company_id, 'sale.confirmed', 'sale', gen_random_uuid(),
                        CAST(:payload AS jsonb))
                RETURNING id
                """
            ),
            {
                "company_id": tenant_a.company_id,
                "payload": json.dumps({"customer": PAYLOAD_CUSTOMER, "total": PAYLOAD_AMOUNT}),
            },
        ).scalar_one()
    with owner_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE coges_bus"))
        connection.execute(
            text("UPDATE business_events SET attempts = 10 WHERE id = :id"), {"id": event_id}
        )
    yield int(event_id)
    bury_dead_letters(owner_engine)


# ------------------------------------------------------------------- job-runs


@pytest.mark.usefixtures("runs")
def test_job_runs_are_sorted_newest_first_within_90_days(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.get(JOB_RUNS, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert (body["page"], body["page_size"]) == (1, 20)
    items = body["items"]
    assert all(set(item) == RUN_KEYS for item in items)
    started = [item["started_at"] for item in items]
    assert started == sorted(started, reverse=True)
    assert items[0]["job"] == PURGE_JOB_RUNS


@pytest.mark.usefixtures("runs")
def test_a_stale_running_trace_reads_as_failed(client: TestClient, headers: dict[str, str]) -> None:
    body = client.get(JOB_RUNS, headers=headers, params={"status": "failed"}).json()
    assert body["total"] == 2
    assert {item["status"] for item in body["items"]} == {"failed"}
    errors = {item["error"] for item in body["items"]}
    assert errors == {"OperationalError", None}


@pytest.mark.usefixtures("runs")
def test_job_runs_filter_by_job_and_paginate(client: TestClient, headers: dict[str, str]) -> None:
    body = client.get(
        JOB_RUNS, headers=headers, params={"job": REBUILD_STOCK, "page": 2, "page_size": 2}
    ).json()
    assert body["total"] == 3
    assert [item["job"] for item in body["items"]] == [REBUILD_STOCK]


@pytest.mark.usefixtures("runs")
def test_a_company_subtask_is_flagged_never_named(
    client: TestClient, headers: dict[str, str], tenant_a: Tenant
) -> None:
    subtask = JOB_FRESHNESS[REBUILD_STOCK].per_company
    response = client.get(JOB_RUNS, headers=headers, params={"job": subtask})
    [item] = response.json()["items"]
    assert item["per_company"] is True
    assert str(tenant_a.company_id) not in response.text
    assert tenant_a.slug not in response.text


@pytest.mark.parametrize(
    "params",
    [{"status": "lost"}, {"job": "inconnue.tache"}, {"page_size": 101}, {"page": 0}],
)
def test_job_runs_refuse_unknown_filters(
    client: TestClient, headers: dict[str, str], params: dict[str, Any]
) -> None:
    response = client.get(JOB_RUNS, headers=headers, params=params)
    assert response.status_code == 422


# --------------------------------------------------------------------- outbox


def test_outbox_lists_dead_letters_without_their_content(
    client: TestClient, headers: dict[str, str], dead_letter: int, tenant_a: Tenant
) -> None:
    response = client.get(OUTBOX, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"lag", "dead_letters"}
    assert body["lag"]["dead_lettered"] >= 1
    page = body["dead_letters"]
    assert page["total"] == body["lag"]["dead_lettered"]
    [mine] = [item for item in page["items"] if item["id"] == dead_letter]
    assert set(mine) == DEAD_LETTER_KEYS
    assert (mine["event_type"], mine["attempts"]) == ("sale.confirmed", 10)
    for secret in (PAYLOAD_CUSTOMER, PAYLOAD_AMOUNT, str(tenant_a.company_id), tenant_a.slug):
        assert secret not in response.text


def test_outbox_without_dead_letters_is_an_empty_page(
    client: TestClient, headers: dict[str, str], owner_engine: Engine
) -> None:
    bury_dead_letters(owner_engine)
    body = client.get(OUTBOX, headers=headers).json()
    assert body["dead_letters"] == {"items": [], "page": 1, "page_size": 20, "total": 0}
    assert body["lag"]["dead_lettered"] == 0


# ----------------------------------------------------------------- portes


@pytest.mark.parametrize("url", [JOB_RUNS, OUTBOX])
def test_both_platform_profiles_read(client: TestClient, url: str) -> None:
    for role in ("administrator", "support"):
        token = platform_login(client, create_platform_account(role))
        assert client.get(url, headers=auth_headers(token)).status_code == 200


@pytest.mark.parametrize("url", [JOB_RUNS, OUTBOX])
def test_neither_a_merchant_nor_the_ops_token_opens_them(
    client: TestClient, company_alpha: DemoCompany, url: str
) -> None:
    """Ces routes sont celles de l'équipe : ni un gérant, ni le jeton du terminal."""
    merchant = login_token(client, company_alpha)
    assert client.get(url, headers=auth_headers(merchant)).status_code == 401
    assert client.get(url, headers=auth_headers(OPS_TOKEN)).status_code == 401
    assert client.get(url).status_code == 401
