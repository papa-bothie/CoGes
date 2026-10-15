"""Réglages du lot 3e-2 de la phase 15 (ADR 0075) : écrans 24 à 24d.

* la grille « Qui peut faire quoi » coche une ligne quand le rôle porte toutes ses
  permissions, garde les droits hors grille et refuse le gérant ;
* couper l'accès d'une personne date la coupure, le lui redonner l'efface ;
* le reçu par défaut est « ticket » ou « a4 », rien d'autre ;
* l'Historique raconte le journal en phrases, sans le geste courant.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    TEST_PASSWORD,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    write_headers,
)

pytestmark = pytest.mark.integration


def _fresh(client: TestClient) -> tuple[DemoCompany, str]:
    company = _create_demo_company(f"lot-3e2-{uuid4().hex[:8]}")
    return company, login_token(client, company)


def _grid(client: TestClient, token: str) -> dict[str, Any]:
    response = client.get("/api/v1/roles/abilities", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _role(grid: dict[str, Any], name: str) -> dict[str, Any]:
    return next(role for role in grid["roles"] if role["name"] == name)


def _permissions(client: TestClient, token: str, role_id: str) -> set[str]:
    detail = client.get(f"/api/v1/roles/{role_id}", headers=auth_headers(token)).json()
    return set(detail["permissions"])


def _set(client: TestClient, token: str, role_id: str, abilities: list[str]) -> Any:
    return client.put(
        f"/api/v1/roles/{role_id}/abilities",
        headers=auth_headers(token),
        json={"abilities": abilities},
    )


# ------------------------------------------------------------------- la grille


def test_the_grid_lists_eight_lines_and_three_system_roles(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    grid = _grid(api_client, token)
    assert [line["label"] for line in grid["abilities"]] == [
        "Vendre",
        "Annuler une vente",
        "Corriger le stock",
        "Recevoir une livraison",
        "Voir l’argent et les bénéfices",
        "Encaisser une dette",
        "Changer les prix",
        "Gérer les personnes",
    ]
    assert [line["key"] for line in grid["abilities"] if line["locked"]] == ["manage_people"]
    assert [(role["name"], role["label"], role["locked"]) for role in grid["roles"]] == [
        ("gerant", "Gérant", True),
        ("vendeur", "Vendeur", False),
        ("comptable", "Comptable", False),
    ]
    assert len(_role(grid, "gerant")["abilities"]) == 8
    # Le vendeur vend, mais sans `debts:read` il n'encaisse pas une dette.
    assert _role(grid, "vendeur")["abilities"] == ["sell"]
    assert set(_role(grid, "comptable")["abilities"]) == {"see_money", "collect_debt"}


def test_ticking_a_line_adds_its_permissions_and_keeps_the_others(
    api_client: TestClient,
) -> None:
    _, token = _fresh(api_client)
    seller = _role(_grid(api_client, token), "vendeur")
    before = _permissions(api_client, token, seller["role_id"])

    ticked = _set(api_client, token, seller["role_id"], ["sell", "collect_debt", "fix_stock"])
    assert ticked.status_code == 200, ticked.text
    assert ticked.json()["abilities"] == ["sell", "fix_stock", "collect_debt"]
    after = _permissions(api_client, token, seller["role_id"])
    assert {"debts:read", "inventory:create", "inventory:update"} <= after
    # Hors grille, rien ne bouge : le vendeur lit toujours ses ventes et ses alertes.
    assert {"sales:read", "notifications:read", "customers:create"} <= after

    # Décocher « Corriger le stock » retire ses deux droits, aucun autre.
    unticked = _set(api_client, token, seller["role_id"], ["sell", "collect_debt"])
    assert unticked.status_code == 200, unticked.text
    final = _permissions(api_client, token, seller["role_id"])
    assert "inventory:update" not in final and "inventory:create" not in final
    assert final == (before | {"debts:read"})


def test_a_shared_permission_stays_while_another_ticked_line_needs_it(
    api_client: TestClient,
) -> None:
    _, token = _fresh(api_client)
    seller = _role(_grid(api_client, token), "vendeur")
    _set(api_client, token, seller["role_id"], ["sell", "fix_stock", "receive"])
    kept = _set(api_client, token, seller["role_id"], ["sell", "receive"])
    assert kept.json()["abilities"] == ["sell", "receive"]
    permissions = _permissions(api_client, token, seller["role_id"])
    assert "inventory:create" in permissions and "inventory:update" not in permissions


def test_the_manager_column_and_the_people_line_are_locked(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    grid = _grid(api_client, token)
    manager = _role(grid, "gerant")
    refused = _set(api_client, token, manager["role_id"], ["sell"])
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "role_locked"

    seller = _role(grid, "vendeur")
    people = _set(api_client, token, seller["role_id"], ["sell", "manage_people"])
    assert people.status_code == 422
    unknown = _set(api_client, token, seller["role_id"], ["sell", "fly"])
    assert unknown.status_code == 422


def test_a_ticked_line_takes_effect_for_the_person(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    seller = _role(_grid(api_client, token), "vendeur")
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={
            "full_name": "Modou Sène",
            "email": "modou@example.com",
            "password": TEST_PASSWORD,
            "role_ids": [seller["role_id"]],
        },
    )
    assert created.status_code == 201, created.text
    logged = api_client.post(
        "/api/v1/auth/login",
        json={
            "company_slug": company.slug,
            "identifier": "modou@example.com",
            "password": TEST_PASSWORD,
        },
    )
    modou = logged.json()["access_token"]
    assert api_client.get("/api/v1/debts", headers=auth_headers(modou)).status_code == 403

    _set(api_client, token, seller["role_id"], ["sell", "collect_debt"])
    assert api_client.get("/api/v1/debts", headers=auth_headers(modou)).status_code == 200


def test_changing_the_grid_is_audited(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    seller = _role(_grid(api_client, token), "vendeur")
    _set(api_client, token, seller["role_id"], ["sell", "cancel_sale"])
    logs = api_client.get(
        f"/api/v1/audit-logs?entity_table=roles&entity_id={seller['role_id']}",
        headers=auth_headers(token),
    ).json()
    assert logs["total"] == 1
    diff = logs["items"][0]["diff"]
    assert diff["after"]["abilities"] == ["cancel_sale", "sell"]
    assert "sales:cancel" in diff["after"]["permissions"]


# ---------------------------------------------------------- accès et réglages


def test_cutting_access_dates_it_and_giving_it_back_clears_it(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    seller = _role(_grid(api_client, token), "vendeur")
    awa = api_client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={"full_name": "Awa Ndiaye", "phone": "770001122", "role_ids": [seller["role_id"]]},
    ).json()
    assert awa["deactivated_at"] is None

    cut = api_client.patch(
        f"/api/v1/users/{awa['id']}", headers=auth_headers(token), json={"is_active": False}
    )
    assert cut.status_code == 200, cut.text
    assert cut.json()["deactivated_at"] is not None

    back = api_client.patch(
        f"/api/v1/users/{awa['id']}", headers=auth_headers(token), json={"is_active": True}
    )
    assert back.json()["deactivated_at"] is None


def test_the_default_receipt_is_a_ticket_or_an_a4_invoice(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    company = api_client.get("/api/v1/companies/me", headers=auth_headers(token)).json()
    saved = api_client.patch(
        "/api/v1/companies/me",
        headers=auth_headers(token),
        json={"settings": {**company["settings"], "receipt_format": "a4"}},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["receipt_format"] == "a4"

    refused = api_client.patch(
        "/api/v1/companies/me",
        headers=auth_headers(token),
        json={"settings": {**company["settings"], "receipt_format": "pdf"}},
    )
    assert refused.status_code == 422


# ------------------------------------------------------------------ historique


def test_history_tells_what_was_done_in_sentences(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    created = api_client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"name": "Riz brisé 25 kg", "unit_price": "15000", "unit": "sac"},
    )
    assert created.status_code == 201, created.text
    rice = created.json()["id"]
    stocked = api_client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={"product_id": rice, "type": "initial", "qty_delta": "10", "unit_cost": "12000"},
    )
    assert stocked.status_code == 201, stocked.text
    priced = api_client.post(
        f"/api/v1/products/{rice}/prices",
        headers=auth_headers(token),
        json={"unit_price": "15500"},
    )
    assert priced.status_code == 201, priced.text
    lost = api_client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={"product_id": rice, "reason_code": "damaged", "qty_delta": "-1"},
    )
    assert lost.status_code == 201, lost.text

    # Une vente confirmée à crédit et sa dette : du geste courant, pas de l'historique.
    customer = api_client.post(
        "/api/v1/customers",
        headers=auth_headers(token),
        json={"name": "Moussa Fall", "credit_limit": "1000000"},
    ).json()
    sale = api_client.post(
        "/api/v1/sales", headers=auth_headers(token), json={"customer_id": customer["id"]}
    ).json()
    api_client.post(
        f"/api/v1/sales/{sale['id']}/items",
        headers=auth_headers(token),
        json={"product_id": rice, "qty": "1"},
    )
    detail = api_client.get(f"/api/v1/sales/{sale['id']}", headers=auth_headers(token)).json()
    confirmed = api_client.post(
        f"/api/v1/sales/{sale['id']}/confirm",
        headers=write_headers(token),
        json={"paid_amount": "0", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    cancelled = api_client.post(
        f"/api/v1/sales/{sale['id']}/cancel",
        headers=auth_headers(token),
        json={"reason": "Enregistrée deux fois"},
    )
    assert cancelled.status_code == 200, cancelled.text

    response = api_client.get("/api/v1/analytics/history", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    lines = response.json()["items"]
    sentences = [line["sentence"].replace(" ", " ").replace("\xa0", " ") for line in lines]
    number = detail["sale_no"].split("-")[-1].lstrip("0")
    assert sentences[0] == f"Gérante a annulé la vente n° {number} (enregistrée deux fois)"
    assert "Gérante a corrigé le stock de Riz brisé 25 kg : −1 sac (abîmé)" in sentences
    assert "Gérante a changé le prix de Riz brisé 25 kg : 15 000 FCFA → 15 500 FCFA" in sentences
    assert "Gérante a ajouté l’article Riz brisé 25 kg à 15 000 FCFA" in sentences
    assert not any("dette" in sentence or "confirmé" in sentence for sentence in sentences)
    assert {line["initials"] for line in lines} == {"GT"}


def test_history_needs_the_audit_permission(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    seller = _role(_grid(api_client, token), "vendeur")
    api_client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={
            "full_name": "Modou Sène",
            "email": "modou@example.com",
            "password": TEST_PASSWORD,
            "role_ids": [seller["role_id"]],
        },
    )
    modou = api_client.post(
        "/api/v1/auth/login",
        json={
            "company_slug": company.slug,
            "identifier": "modou@example.com",
            "password": TEST_PASSWORD,
        },
    ).json()["access_token"]
    assert (
        api_client.get("/api/v1/analytics/history", headers=auth_headers(modou)).status_code == 403
    )
    assert api_client.get("/api/v1/roles/abilities", headers=auth_headers(modou)).status_code == 403
