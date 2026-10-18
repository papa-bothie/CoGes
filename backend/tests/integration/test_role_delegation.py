"""Délégation de droits : personne ne donne plus qu'il n'a (P2.3, ADR 0088).

Deux portes ouvertes à la relecture :

* `POST /users` et `POST /users/{id}/roles` attribuaient n'importe quel rôle de
  l'entreprise, même plus puissant que l'appelant : quelqu'un qui peut créer des
  comptes se faisait gérant ;
* `POST /roles` et `PATCH /roles/{id}` acceptaient `users:*` et `roles:*` sur un rôle
  sur mesure, contournant le verrou de « Gérer les personnes » de la grille (ADR 0075).

Le délégué de ces tests est fabriqué **en SQL** : précisément parce que l'API refuse
désormais de construire son rôle.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from tests.conftest import TEST_PASSWORD, DemoCompany, auth_headers

pytestmark = pytest.mark.integration

#: Le rôle d'un « recruteur » : il crée des comptes et attribue des rôles, sans plus.
DELEGATE_PERMISSIONS = ("users:create", "users:read", "users:update", "roles:read")


def _role_id(client: TestClient, token: str, name: str) -> str:
    roles = client.get("/api/v1/roles?page_size=50", headers=auth_headers(token)).json()
    return str(next(role["id"] for role in roles["items"] if role["name"] == name))


@pytest.fixture
def delegate(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany, owner_engine: Engine
) -> dict[str, Any]:
    """Un compte dont le rôle sur mesure porte `users:create`, posé directement en base."""
    role_id = uuid4()
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :c, true)"),
            {"c": str(company_alpha.company_id)},
        )
        connection.execute(
            text(
                "INSERT INTO roles (id, company_id, name, is_system) "
                "VALUES (:id, :company_id, :name, false)"
            ),
            {
                "id": role_id,
                "company_id": company_alpha.company_id,
                "name": f"rh-{role_id.hex[:6]}",
            },
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions (company_id, role_id, permission_id) "
                "SELECT :company_id, :role_id, id FROM permissions WHERE code = ANY(:codes)"
            ),
            {
                "company_id": company_alpha.company_id,
                "role_id": role_id,
                "codes": list(DELEGATE_PERMISSIONS),
            },
        )
    email = f"rh-{uuid4().hex[:8]}@alpha.example.com"
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(alpha_token),
        json={
            "email": email,
            "full_name": "Recruteur",
            "password": TEST_PASSWORD,
            "role_ids": [str(role_id)],
        },
    )
    assert created.status_code == 201, created.text
    login = api_client.post(
        "/api/v1/auth/login",
        json={"company_slug": company_alpha.slug, "email": email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"token": login.json()["access_token"], "role_id": str(role_id)}


def test_a_delegate_cannot_create_a_manager(
    api_client: TestClient, alpha_token: str, delegate: dict[str, Any]
) -> None:
    manager_role = _role_id(api_client, alpha_token, "gerant")
    refused = api_client.post(
        "/api/v1/users",
        headers=auth_headers(delegate["token"]),
        json={
            "email": f"faux-gerant-{uuid4().hex[:6]}@alpha.example.com",
            "full_name": "Faux gérant",
            "role_ids": [manager_role],
        },
    )
    assert refused.status_code == 403, refused.text


def test_a_delegate_cannot_give_a_manager_role_to_an_existing_account(
    api_client: TestClient, alpha_token: str, delegate: dict[str, Any]
) -> None:
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(delegate["token"]),
        json={"email": f"simple-{uuid4().hex[:6]}@alpha.example.com", "full_name": "Simple"},
    )
    assert created.status_code == 201, created.text

    refused = api_client.post(
        f"/api/v1/users/{created.json()['id']}/roles",
        headers=auth_headers(delegate["token"]),
        json={"role_id": _role_id(api_client, alpha_token, "gerant")},
    )
    assert refused.status_code == 403, refused.text


def test_a_delegate_may_give_a_role_within_its_own_rights(
    api_client: TestClient, delegate: dict[str, Any]
) -> None:
    """Son propre rôle, inclus dans ses droits par définition : accepté."""
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(delegate["token"]),
        json={
            "email": f"collegue-{uuid4().hex[:6]}@alpha.example.com",
            "full_name": "Collègue",
            "role_ids": [delegate["role_id"]],
        },
    )
    assert created.status_code == 201, created.text


@pytest.mark.parametrize("permission", ["users:create", "users:delete", "roles:update"])
def test_a_custom_role_never_carries_people_or_role_rights(
    api_client: TestClient, alpha_token: str, permission: str
) -> None:
    """Même pour le gérant : `users:*` et `roles:*` sont réservés au rôle gérant."""
    headers = auth_headers(alpha_token)
    created = api_client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": f"sur-mesure-{uuid4().hex[:6]}", "permissions": [permission]},
    )
    assert created.status_code == 422, created.text

    plain = api_client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": f"sur-mesure-{uuid4().hex[:6]}", "permissions": ["sales:read"]},
    )
    assert plain.status_code == 201, plain.text
    patched = api_client.patch(
        f"/api/v1/roles/{plain.json()['id']}",
        headers=headers,
        json={"permissions": ["sales:read", permission]},
    )
    assert patched.status_code == 422, patched.text


def test_the_manager_still_creates_any_account(api_client: TestClient, alpha_token: str) -> None:
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(alpha_token),
        json={
            "email": f"second-gerant-{uuid4().hex[:6]}@alpha.example.com",
            "full_name": "Second gérant",
            "role_ids": [_role_id(api_client, alpha_token, "gerant")],
        },
    )
    assert created.status_code == 201, created.text
