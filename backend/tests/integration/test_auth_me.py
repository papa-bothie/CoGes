"""`GET /auth/me` : l'identité de la session, telle que le serveur la juge."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.modules.rbac.matrix import (
    ACCOUNTANT,
    ACCOUNTANT_PERMISSIONS,
    SALESPERSON,
    SALESPERSON_PERMISSIONS,
)
from tests.conftest import DemoCompany, auth_headers, create_user_with_role

pytestmark = pytest.mark.integration


def test_manager_sees_self_company_and_every_permission(
    api_client: TestClient, company_alpha: DemoCompany, alpha_token: str
) -> None:
    response = api_client.get("/api/v1/auth/me", headers=auth_headers(alpha_token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"] == {
        "id": str(company_alpha.manager_id),
        "email": company_alpha.email,
        "phone": None,
        "full_name": "Gérante de test",
        "must_change_password": False,
    }
    assert [(role["name"], role["description"]) for role in body["roles"]] == [("gerant", "Gérant")]
    assert body["company"] == {
        "id": str(company_alpha.company_id),
        "name": "Societe Alpha",
        "slug": company_alpha.slug,
        "currency": "XOF",
        "timezone": "Africa/Dakar",
        "tax_enabled": True,
        "receipt_format": "ticket",
    }
    assert body["permissions"] == sorted(body["permissions"])
    assert "users:read" in body["permissions"]


@pytest.mark.parametrize(
    ("role", "expected"),
    [(SALESPERSON, SALESPERSON_PERMISSIONS), (ACCOUNTANT, ACCOUNTANT_PERMISSIONS)],
)
def test_each_role_reads_exactly_its_matrix_permissions(
    api_client: TestClient,
    company_alpha: DemoCompany,
    alpha_token: str,
    role: str,
    expected: frozenset[str],
) -> None:
    """Sans `users:read` ni `company:read`, un vendeur sait tout de même qui il est."""
    token = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role=role,
        email=f"{role}-{uuid4().hex[:8]}@societe-alpha.example.com",
    )

    response = api_client.get("/api/v1/auth/me", headers=auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["permissions"] == sorted(expected)
    assert [r["name"] for r in body["roles"]] == [role]
    assert body["company"]["id"] == str(company_alpha.company_id)


def test_each_tenant_only_ever_sees_itself(
    api_client: TestClient,
    company_alpha: DemoCompany,
    company_beta: DemoCompany,
    alpha_token: str,
    beta_token: str,
) -> None:
    alpha = api_client.get("/api/v1/auth/me", headers=auth_headers(alpha_token)).json()
    beta = api_client.get("/api/v1/auth/me", headers=auth_headers(beta_token)).json()

    assert alpha["company"]["id"] == str(company_alpha.company_id)
    assert beta["company"]["id"] == str(company_beta.company_id)
    assert beta["user"]["id"] == str(company_beta.manager_id)
    assert {r["id"] for r in alpha["roles"]}.isdisjoint({r["id"] for r in beta["roles"]})


def test_me_requires_an_access_token(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
