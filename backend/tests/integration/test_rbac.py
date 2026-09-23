"""RBAC : 403 dans son propre tenant, 404 chez le voisin.

Un droit manquant chez soi donne **403**. La même ressource chez une autre
entreprise donne **404** : un 403 révélerait son existence.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.modules.rbac.matrix import ACCOUNTANT_PERMISSIONS, SALESPERSON_PERMISSIONS
from tests.conftest import (
    TEST_PASSWORD,
    DemoCompany,
    auth_headers,
    read_scalar_in_tenant,
)

pytestmark = pytest.mark.integration


def _role_id(client: TestClient, token: str, name: str) -> str:
    response = client.get("/api/v1/roles?page_size=50", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return next(role["id"] for role in response.json()["items"] if role["name"] == name)


def _create_user_with_role(
    client: TestClient, token: str, company: DemoCompany, *, role: str, email: str
) -> str:
    """Crée un compte porteur d'un rôle système et renvoie son jeton d'accès."""
    created = client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={
            "email": email,
            "full_name": f"Compte {role}",
            "password": TEST_PASSWORD,
            "role_ids": [_role_id(client, token, role)],
        },
    )
    assert created.status_code == 201, created.text

    login = client.post(
        "/api/v1/auth/login",
        json={"company_slug": company.slug, "email": email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    access_token: str = login.json()["access_token"]
    return access_token


@pytest.fixture
def salesperson_token(api_client: TestClient, company_alpha: DemoCompany, alpha_token: str) -> str:
    # E-mail unique : la fixture est appelée par plusieurs tests, et l'unicité
    # de `users_email_uq` est justement ce que l'on ne veut pas tester ici.
    return _create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="vendeur",
        email=f"vendeur-{uuid4().hex[:8]}@societe-alpha.example.com",
    )


def test_manager_holds_every_permission(api_client: TestClient, alpha_token: str) -> None:
    """Le gérant reçoit tout le catalogue (matrice de l'ADR 0007)."""
    catalogue = api_client.get("/api/v1/permissions", headers=auth_headers(alpha_token))
    assert catalogue.status_code == 200
    assert len(catalogue.json()) >= 50


def test_salesperson_cannot_manage_roles_in_its_own_company(
    api_client: TestClient, salesperson_token: str
) -> None:
    """403 : le droit manque, mais la ressource existe bien dans son entreprise."""
    response = api_client.post(
        "/api/v1/roles",
        headers=auth_headers(salesperson_token),
        json={"name": "role-interdit", "permissions": []},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "permission_denied"
    assert body["error"]["details"]["required_permission"] == "roles:create"


def test_salesperson_cannot_list_users(api_client: TestClient, salesperson_token: str) -> None:
    response = api_client.get("/api/v1/users", headers=auth_headers(salesperson_token))
    assert response.status_code == 403


def test_salesperson_keeps_its_own_permissions() -> None:
    """Le vendeur garde bien ce que la matrice lui accorde : le test n'est pas vide."""
    assert "dashboard:read" in SALESPERSON_PERMISSIONS
    assert "sales:confirm" in SALESPERSON_PERMISSIONS
    assert "sales:cancel" not in SALESPERSON_PERMISSIONS
    assert "inventory:update" not in SALESPERSON_PERMISSIONS


def test_accountant_cannot_confirm_a_sale_or_touch_stock() -> None:
    """Arbitrages de la matrice, vérifiés sur la source (ADR 0007)."""
    assert "sales:confirm" not in ACCOUNTANT_PERMISSIONS
    assert "inventory:update" not in ACCOUNTANT_PERMISSIONS
    assert "payments:cancel" in ACCOUNTANT_PERMISSIONS
    assert "audit:read" in ACCOUNTANT_PERMISSIONS


def test_role_of_another_company_is_not_found(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """404, jamais 403 : le rôle de l'entreprise voisine n'existe pas pour alpha."""
    beta_role = _role_id(api_client, beta_token, "vendeur")

    response = api_client.get(f"/api/v1/roles/{beta_role}", headers=auth_headers(alpha_token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_user_of_another_company_is_not_found(
    api_client: TestClient, alpha_token: str, company_beta: DemoCompany
) -> None:
    response = api_client.get(
        f"/api/v1/users/{company_beta.manager_id}", headers=auth_headers(alpha_token)
    )

    assert response.status_code == 404


def test_assigning_a_foreign_role_is_not_found(
    api_client: TestClient,
    alpha_token: str,
    beta_token: str,
    company_alpha: DemoCompany,
) -> None:
    """Attribuer le rôle d'une autre entreprise est impossible, et indiscernable."""
    beta_role = _role_id(api_client, beta_token, "comptable")

    response = api_client.post(
        f"/api/v1/users/{company_alpha.manager_id}/roles",
        headers=auth_headers(alpha_token),
        json={"role_id": beta_role},
    )

    assert response.status_code == 404


def test_system_roles_cannot_be_deleted(api_client: TestClient, alpha_token: str) -> None:
    role_id = _role_id(api_client, alpha_token, "gerant")

    response = api_client.delete(f"/api/v1/roles/{role_id}", headers=auth_headers(alpha_token))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_revoking_a_role_is_audited(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Retirer un rôle supprime la ligne de liaison, mais laisse une trace d'audit."""
    role_id = _role_id(api_client, alpha_token, "comptable")
    user_id = str(company_alpha.manager_id)

    assigned = api_client.post(
        f"/api/v1/users/{user_id}/roles",
        headers=auth_headers(alpha_token),
        json={"role_id": role_id},
    )
    assert assigned.status_code == 200
    assert role_id in assigned.json()

    revoked = api_client.delete(
        f"/api/v1/users/{user_id}/roles/{role_id}", headers=auth_headers(alpha_token)
    )
    assert revoked.status_code == 200
    assert role_id not in revoked.json()

    traces = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs WHERE entity_table = 'user_roles' AND entity_id = :id",
        {"id": user_id},
    )
    assert traces >= 2, "l'attribution et la révocation doivent laisser une trace chacune"


def test_unknown_permission_code_is_refused(api_client: TestClient, alpha_token: str) -> None:
    response = api_client.post(
        "/api/v1/roles",
        headers=auth_headers(alpha_token),
        json={"name": "role-invalide", "permissions": ["ceci:nexiste_pas"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["unknown_permissions"] == ["ceci:nexiste_pas"]
