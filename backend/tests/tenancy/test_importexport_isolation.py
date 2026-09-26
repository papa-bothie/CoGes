"""Import/Export et isolation (Diagramme 8 : « agrégats et exports » étanches).

Un import dans A est invisible de B ; un export de A ne contient aucune donnée de B et
reste introuvable (404) depuis B.
"""

from __future__ import annotations

import csv
import io
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, write_headers

pytestmark = pytest.mark.tenancy


def _names(response: Any) -> set[str]:
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    return {row[0] for row in rows[1:]}


def test_import_in_a_is_invisible_from_b(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    marker = uuid4().hex[:8]
    content = f"nom;code\nClient isolé {marker};ISO-{marker}\n".encode()
    imported = api_client.post(
        "/api/v1/imports/customers",
        headers=write_headers(alpha_token),
        files={"file": ("clients.csv", content, "text/csv")},
    )
    assert imported.status_code == 201, imported.text

    seen_by_beta = api_client.get(
        "/api/v1/customers", params={"search": marker}, headers=auth_headers(beta_token)
    ).json()
    assert seen_by_beta["total"] == 0
    # Et le même code reste libre chez B : l'unicité est par entreprise.
    beta_import = api_client.post(
        "/api/v1/imports/customers",
        headers=write_headers(beta_token),
        files={"file": ("clients.csv", content, "text/csv")},
    )
    assert beta_import.status_code == 201, beta_import.text


def test_referential_export_contains_only_own_data(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    marker = uuid4().hex[:8]
    api_client.post(
        "/api/v1/suppliers", headers=auth_headers(beta_token), json={"name": f"Beta {marker}"}
    )

    exported = api_client.get(
        "/api/v1/exports/referentials/suppliers",
        params={"format": "csv"},
        headers=auth_headers(alpha_token),
    )

    assert exported.status_code == 200
    assert f"Beta {marker}" not in _names(exported)


def test_sales_export_of_a_is_not_found_from_b(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    export_id = api_client.post(
        "/api/v1/exports/sales",
        headers=auth_headers(alpha_token),
        json={"date_from": "2026-01-01", "date_to": "2026-01-31"},
    ).json()["id"]

    for path in (f"/api/v1/exports/{export_id}", f"/api/v1/exports/{export_id}/file"):
        response = api_client.get(path, headers=auth_headers(beta_token))
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "not_found"
    listed = api_client.get("/api/v1/exports", headers=auth_headers(beta_token)).json()
    assert export_id not in {item["id"] for item in listed["items"]}
