"""Exports (phase 10, ADR 0041) : référentiels dans la requête, ventes par le worker.

L'API enfile la tâche par son nom ; ici, l'enfilement est intercepté et la tâche est
exécutée en direct sur la base de test — même code que le conteneur worker.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core import queue
from app.core.tenancy import TenantContext, tenant_transaction
from app.workers.tasks import exports as export_tasks
from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def record(task_name: str, *, countdown: int = 0, **kwargs: Any) -> bool:
        calls.append((task_name, kwargs))
        return True

    monkeypatch.setattr(queue, "enqueue", record)
    return calls


def _request(client: TestClient, token: str, **body: Any) -> Any:
    today = date.today()
    payload = {
        "date_from": (today - timedelta(days=30)).isoformat(),
        "date_to": today.isoformat(),
        "format": "csv",
        **body,
    }
    return client.post("/api/v1/exports/sales", headers=auth_headers(token), json=payload)


def test_sales_export_is_built_by_the_worker_and_served(
    api_client: TestClient,
    alpha_token: str,
    workers_bound_to_test_database: None,
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    requested = _request(api_client, alpha_token)
    assert requested.status_code == 202, requested.text
    export_id = requested.json()["id"]
    assert requested.json()["status"] == "pending"

    # Pas encore prêt : 409, pas 404.
    early = api_client.get(f"/api/v1/exports/{export_id}/file", headers=auth_headers(alpha_token))
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "export_not_ready"

    [(task_name, kwargs)] = [call for call in enqueued if call[0] == "exports.build_sales"]
    assert export_tasks.build_sales(**kwargs) == "ready"
    # Deuxième livraison de la même tâche : sans effet.
    assert export_tasks.build_sales(**kwargs) == "ready"

    status = api_client.get(f"/api/v1/exports/{export_id}", headers=auth_headers(alpha_token))
    assert status.json()["status"] == "ready"
    downloaded = api_client.get(
        f"/api/v1/exports/{export_id}/file", headers=auth_headers(alpha_token)
    )
    assert downloaded.status_code == 200
    rows = list(csv.reader(io.StringIO(downloaded.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:4] == ["numero", "date", "statut", "client"]
    assert len(rows) - 1 == status.json()["row_count"]


def test_export_is_traced_in_the_secondary_audit(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    workers_bound_to_test_database: None,
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    export_id = _request(api_client, alpha_token).json()["id"]
    [(_, kwargs)] = [call for call in enqueued if call[0] == "exports.build_sales"]
    export_tasks.build_sales(**kwargs)

    traced = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs WHERE entity_table = 'export_files' "
        "AND entity_id = :id AND action = 'export'",
        {"id": export_id},
    )
    assert traced == 1

    api_client.get("/api/v1/exports/referentials/customers", headers=auth_headers(alpha_token))
    assert any(name == "audit.record" for name, _ in enqueued)


def test_expired_export_is_emptied_but_kept(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    workers_bound_to_test_database: None,
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    export_id = _request(api_client, alpha_token).json()["id"]
    [(_, kwargs)] = [call for call in enqueued if call[0] == "exports.build_sales"]
    export_tasks.build_sales(**kwargs)

    ctx = TenantContext.bootstrap(company_alpha.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        session.execute(
            text("UPDATE export_files SET expires_at = :past WHERE id = :id"),
            {"past": datetime.now(UTC) - timedelta(minutes=1), "id": export_id},
        )
    export_tasks.sweep(str(company_alpha.company_id))

    status = api_client.get(f"/api/v1/exports/{export_id}", headers=auth_headers(alpha_token))
    assert status.json()["status"] == "expired"
    assert (
        read_scalar_in_tenant(
            session_factory,
            company_alpha.company_id,
            "SELECT content IS NULL FROM export_files WHERE id = :id",
            {"id": export_id},
        )
        is True
    )
    gone = api_client.get(f"/api/v1/exports/{export_id}/file", headers=auth_headers(alpha_token))
    assert gone.status_code == 409


def test_sweep_requeues_a_request_left_pending(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    workers_bound_to_test_database: None,
    enqueued: list[tuple[str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis indisponible au moment de la demande : le balayage nocturne la renfile."""
    export_id = UUID(_request(api_client, alpha_token).json()["id"])
    delayed: list[dict[str, Any]] = []
    monkeypatch.setattr(export_tasks.build_sales, "delay", lambda **kwargs: delayed.append(kwargs))

    export_tasks.sweep(str(company_alpha.company_id))

    assert str(export_id) in {kwargs["export_id"] for kwargs in delayed}


def test_period_longer_than_a_year_is_refused(api_client: TestClient, alpha_token: str) -> None:
    response = _request(api_client, alpha_token, date_from="2025-01-01", date_to="2026-06-01")
    assert response.status_code == 422
