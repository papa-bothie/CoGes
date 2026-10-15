"""Le journal d'activité (ADR 0053) ne montre que l'entreprise du contexte.

La requête pose `company_id` et la RLS de chaque partition le pose aussi : même un
filtre qui vise précisément une entité d'une autre entreprise revient vide.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers

pytestmark = pytest.mark.tenancy


def test_audit_logs_never_cross_the_tenant(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    created = api_client.post(
        "/api/v1/suppliers",
        headers=auth_headers(alpha_token),
        json={"name": f"Fournisseur {uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    supplier_id = created.json()["id"]
    deleted = api_client.delete(
        f"/api/v1/suppliers/{supplier_id}", headers=auth_headers(alpha_token)
    )
    assert deleted.status_code in (200, 204), deleted.text

    own = api_client.get(
        f"/api/v1/audit-logs?entity_id={supplier_id}", headers=auth_headers(alpha_token)
    ).json()
    assert own["total"] >= 1

    foreign = api_client.get(
        f"/api/v1/audit-logs?entity_id={supplier_id}", headers=auth_headers(beta_token)
    )
    assert foreign.status_code == 200, foreign.text
    assert foreign.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}

    everything = api_client.get(
        "/api/v1/audit-logs?page_size=100", headers=auth_headers(beta_token)
    ).json()
    assert supplier_id not in {item["entity_id"] for item in everything["items"]}


def test_history_and_ability_grid_never_cross_the_tenant(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """Historique et grille (ADR 0075) : composés par façades, donc sous le même filtre."""
    name = f"Fournisseur {uuid4().hex[:8]}"
    created = api_client.post(
        "/api/v1/suppliers", headers=auth_headers(alpha_token), json={"name": name}
    )
    supplier_id = created.json()["id"]
    api_client.delete(f"/api/v1/suppliers/{supplier_id}", headers=auth_headers(alpha_token))

    own = api_client.get(
        "/api/v1/analytics/history?page_size=50", headers=auth_headers(alpha_token)
    )
    assert own.status_code == 200, own.text
    assert own.json()["total"] >= 1
    foreign = api_client.get(
        "/api/v1/analytics/history?page_size=50", headers=auth_headers(beta_token)
    ).json()
    alpha_ids = {line["id"] for line in own.json()["items"]}
    assert alpha_ids.isdisjoint({line["id"] for line in foreign["items"]})

    alpha_roles = {
        role["role_id"]
        for role in api_client.get(
            "/api/v1/roles/abilities", headers=auth_headers(alpha_token)
        ).json()["roles"]
    }
    beta_roles = {
        role["role_id"]
        for role in api_client.get(
            "/api/v1/roles/abilities", headers=auth_headers(beta_token)
        ).json()["roles"]
    }
    assert alpha_roles and beta_roles and alpha_roles.isdisjoint(beta_roles)
