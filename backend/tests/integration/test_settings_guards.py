"""Paramètres de la phase 13 (ADR 0054).

* les réglages connus de l'entreprise sont vérifiés (booléens, seuil en chaîne) ;
* le seuil par défaut s'applique à un produit suivi créé sans seuil, et à lui seul ;
* aucune action ne laisse l'entreprise sans gérant actif, et nul ne se désactive.

Chaque test travaille sur **sa** entreprise : un réglage ou un gérant de plus sur
l'entreprise partagée fausserait les autres fichiers.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    create_user_with_role,
    login_token,
    role_id,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def company(app_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"reglages-{uuid4().hex[:8]}")


def _product(client: TestClient, token: str, **extra: Any) -> dict[str, Any]:
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"sku": f"SEU-{marker}", "name": f"Article {marker}", "unit_price": "100", **extra},
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def test_known_settings_are_checked(api_client: TestClient, company: DemoCompany) -> None:
    token = login_token(api_client, company)
    for settings in (
        {"tax_enabled": "oui"},
        {"intelligence_enabled": 1},
        {"default_reorder_point": 5},
        {"default_reorder_point": "-1"},
        {"default_reorder_point": "1.2345"},
        {"default_reorder_point": "abc"},
    ):
        refused = api_client.patch(
            "/api/v1/companies/me", headers=auth_headers(token), json={"settings": settings}
        )
        assert refused.status_code == 422, (settings, refused.text)

    accepted = api_client.patch(
        "/api/v1/companies/me",
        headers=auth_headers(token),
        json={"settings": {"tax_enabled": False, "default_reorder_point": "5.50", "x": 1}},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["settings"] == {
        "tax_enabled": False,
        "default_reorder_point": "5.50",
        "x": 1,
    }


def test_the_default_reorder_point_fills_only_a_missing_one(
    api_client: TestClient, company: DemoCompany
) -> None:
    token = login_token(api_client, company)
    assert _product(api_client, token)["reorder_point"] is None

    api_client.patch(
        "/api/v1/companies/me",
        headers=auth_headers(token),
        json={"settings": {"default_reorder_point": "5"}},
    )
    assert _product(api_client, token)["reorder_point"] == "5.000"
    assert _product(api_client, token, reorder_point="0")["reorder_point"] == "0.000"
    assert _product(api_client, token, reorder_point="12")["reorder_point"] == "12.000"
    untracked = _product(api_client, token, is_stock_tracked=False)
    assert untracked["reorder_point"] is None


def test_the_last_active_manager_cannot_be_removed(
    api_client: TestClient, company: DemoCompany
) -> None:
    token = login_token(api_client, company)
    manager_role = role_id(api_client, token, "gerant")
    me = company.manager_id

    # Se désactiver soi-même : refusé par PATCH comme par DELETE.
    own = api_client.patch(
        f"/api/v1/users/{me}", headers=auth_headers(token), json={"is_active": False}
    )
    assert own.status_code == 422, own.text

    # Seul gérant : son rôle ne peut pas lui être retiré.
    revoked = api_client.delete(
        f"/api/v1/users/{me}/roles/{manager_role}", headers=auth_headers(token)
    )
    assert revoked.status_code == 409, revoked.text
    assert revoked.json()["error"]["code"] == "last_manager"

    # Un second gérant, puis désactivé : il ne compte plus, le premier reste le dernier.
    email = f"second-{uuid4().hex[:6]}@{company.slug}.example.com"
    create_user_with_role(api_client, token, company, role="gerant", email=email)
    second = next(
        user
        for user in api_client.get("/api/v1/users", headers=auth_headers(token)).json()["items"]
        if user["email"] == email
    )
    deactivated = api_client.patch(
        f"/api/v1/users/{second['id']}", headers=auth_headers(token), json={"is_active": False}
    )
    assert deactivated.status_code == 200, deactivated.text
    still_last = api_client.delete(
        f"/api/v1/users/{me}/roles/{manager_role}", headers=auth_headers(token)
    )
    assert still_last.status_code == 409

    # Réactivé, le second gérant rend le retrait possible.
    reactivated = api_client.patch(
        f"/api/v1/users/{second['id']}", headers=auth_headers(token), json={"is_active": True}
    )
    assert reactivated.status_code == 200
    allowed = api_client.delete(
        f"/api/v1/users/{me}/roles/{manager_role}", headers=auth_headers(token)
    )
    assert allowed.status_code == 200, allowed.text


def test_the_last_manager_cannot_be_deactivated_by_another_user(
    api_client: TestClient, company: DemoCompany, owner_engine: Engine
) -> None:
    """Un compte doté de `users:update` sans être gérant ne peut pas désarmer le dernier.

    Le rôle est posé en base : l'API refuse désormais `users:*` sur un rôle sur mesure
    (ADR 0088), mais la garde du dernier gérant doit tenir même si un tel rôle existe.
    """
    token = login_token(api_client, company)
    name = f"rh-{uuid4().hex[:6]}"
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(company.company_id)}
        )
        role_id = connection.execute(
            text(
                "INSERT INTO roles (company_id, name, is_system) "
                "VALUES (:company_id, :name, false) RETURNING id"
            ),
            {"company_id": company.company_id, "name": name},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO role_permissions (company_id, role_id, permission_id) "
                "SELECT :company_id, :role_id, id FROM permissions WHERE code = ANY(:codes)"
            ),
            {
                "company_id": company.company_id,
                "role_id": role_id,
                "codes": ["users:read", "users:update", "users:delete"],
            },
        )
    hr = create_user_with_role(
        api_client, token, company, role=name, email=f"{name}@{company.slug}.example.com"
    )

    patched = api_client.patch(
        f"/api/v1/users/{company.manager_id}",
        headers=auth_headers(hr),
        json={"is_active": False},
    )
    assert patched.status_code == 409, patched.text
    deleted = api_client.delete(f"/api/v1/users/{company.manager_id}", headers=auth_headers(hr))
    assert deleted.status_code == 409, deleted.text
