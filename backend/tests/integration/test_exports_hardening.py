"""Exports : plafond, idempotence, catégories réimportables (P2.24, ADR 0088).

* Chaque demande d'export des ventes enfilait une tâche qui construit tout le fichier en
  mémoire : un double clic, ou un script, empilait les exports sans limite.
* Une demande rejouée (réseau coupé, double clic) créait un second export.
* L'export des catégories nommait le parent par son seul nom ; deux « Lait » sous deux
  rayons, et la sous-catégorie ne se réimportait plus (`category_ambiguous`).
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    write_headers,
)

pytestmark = pytest.mark.integration

EXPORTS = "/api/v1/exports/sales"


@pytest.fixture
def shop(app_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"export-{uuid4().hex[:6]}")


def _ask(client: TestClient, token: str, key: str | None = None) -> Any:
    today = date.today().isoformat()
    return client.post(
        EXPORTS,
        headers=write_headers(token, key),
        json={"date_from": today, "date_to": today, "format": "csv"},
    )


def test_pending_sales_exports_are_capped(
    api_client: TestClient, shop: DemoCompany, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.modules.importexport.service.MAX_PENDING_EXPORTS", 3)
    token = login_token(api_client, shop)
    statuses = [_ask(api_client, token).status_code for _ in range(4)]
    assert statuses[:3] == [202, 202, 202]
    assert statuses[3] == 409, f"quatrième export en attente accepté : {statuses}"


def test_a_replayed_request_gives_the_same_export(
    api_client: TestClient, shop: DemoCompany, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued: list[str] = []
    monkeypatch.setattr(
        "app.modules.importexport.router.queue.enqueue",
        lambda *a, **k: queued.append(k["export_id"]) or True,
    )
    token = login_token(api_client, shop)
    key = str(uuid4())

    first = _ask(api_client, token, key)
    second = _ask(api_client, token, key)

    assert first.status_code == 202, first.text
    assert second.json()["id"] == first.json()["id"], "la demande rejouée crée un second export"
    assert len(queued) == 1


def test_a_sales_export_requires_an_idempotency_key(
    api_client: TestClient, shop: DemoCompany
) -> None:
    """Client brut : `api_client` ajoute de lui-même une clé à chaque écriture."""
    token = login_token(api_client, shop)
    today = date.today().isoformat()
    with TestClient(app, base_url=TEST_BASE_URL) as raw:
        response = raw.post(
            EXPORTS, headers=auth_headers(token), json={"date_from": today, "date_to": today}
        )
    assert response.status_code == 422, response.text


def test_exported_categories_import_back_with_same_named_parents(
    api_client: TestClient, shop: DemoCompany
) -> None:
    token = login_token(api_client, shop)
    headers = auth_headers(token)

    def category(name: str, parent: str | None = None) -> str:
        body: dict[str, Any] = {"name": name, **({"parent_id": parent} if parent else {})}
        created = api_client.post("/api/v1/categories", headers=headers, json=body)
        assert created.status_code == 201, created.text
        return str(created.json()["id"])

    drinks, fresh = category("Boissons"), category("Frais")
    category("Entier", category("Lait", drinks))
    category("Lait", fresh)

    exported = api_client.get(
        "/api/v1/exports/referentials/categories", headers=headers, params={"format": "csv"}
    )
    assert exported.status_code == 200, exported.text

    target = _create_demo_company(f"reimport-{uuid4().hex[:6]}")
    target_token = login_token(api_client, target)
    imported = api_client.post(
        "/api/v1/imports/categories",
        headers=write_headers(target_token),
        files={"file": ("categories.csv", exported.content, "text/csv")},
    )
    assert imported.status_code == 201, imported.text
