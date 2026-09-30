"""Lectures et écriture ajoutées pour les écrans de pilotage (ADR 0053).

* `UserRead.roles`, `DebtDetail.party_name`, `ExpenseRead.amount_paid` disent vrai ;
* une dépense « payée maintenant » s'écrit avec son décaissement dans **une**
  transaction : un refus du paiement annule aussi la dépense, un rejeu ne double rien ;
* `GET /audit-logs` lit le journal, filtré, auteur nommé, gérant et comptable seuls.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DemoCompany, auth_headers, create_user_with_role, write_headers

pytestmark = pytest.mark.integration

EXPENSES = "/api/v1/expenses"
AUDIT = "/api/v1/audit-logs"


def _category(client: TestClient, token: str) -> str:
    created = client.post(
        "/api/v1/expense-categories",
        headers=auth_headers(token),
        json={"name": f"Charge {uuid4().hex[:8]}", "kind": "fixed"},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _expense_body(category_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "category_id": category_id,
        "label": f"Loyer {uuid4().hex[:6]}",
        "amount": "75000.00",
        "spent_at": date.today().isoformat(),
        **extra,
    }


def _payments_of_expense(client: TestClient, token: str, expense_id: str) -> list[dict[str, Any]]:
    listed = client.get(
        "/api/v1/payments?direction=outflow&page_size=100", headers=auth_headers(token)
    )
    assert listed.status_code == 200, listed.text
    return [p for p in listed.json()["items"] if p["expense_id"] == expense_id]


# ---------------------------------------------------------------- enrichissements


def test_the_user_list_carries_the_roles(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    email = f"compta-{uuid4().hex[:8]}@societe-alpha.example.com"
    create_user_with_role(api_client, alpha_token, company_alpha, role="comptable", email=email)

    listed = api_client.get("/api/v1/users?page_size=100", headers=auth_headers(alpha_token))
    assert listed.status_code == 200, listed.text
    user = next(item for item in listed.json()["items"] if item["email"] == email)
    assert [role["name"] for role in user["roles"]] == ["comptable"]

    detail = api_client.get(f"/api/v1/users/{user['id']}", headers=auth_headers(alpha_token))
    assert [role["name"] for role in detail.json()["roles"]] == ["comptable"]


def test_a_debt_names_its_party(api_client: TestClient, alpha_token: str) -> None:
    supplier = api_client.post(
        "/api/v1/suppliers",
        headers=auth_headers(alpha_token),
        json={"name": f"Fournisseur {uuid4().hex[:8]}"},
    ).json()
    created = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={"party_type": "supplier", "supplier_id": supplier["id"], "principal": "12000"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["party_name"] == supplier["name"]

    listed = api_client.get(
        f"/api/v1/debts?supplier_id={supplier['id']}", headers=auth_headers(alpha_token)
    ).json()
    assert [debt["party_name"] for debt in listed["items"]] == [supplier["name"]]

    detail = api_client.get(
        f"/api/v1/debts/{created.json()['id']}", headers=auth_headers(alpha_token)
    ).json()
    assert detail["party_name"] == supplier["name"]


# ------------------------------------------------------------- dépense payée


def test_an_expense_paid_now_is_written_with_its_outflow(
    api_client: TestClient, alpha_token: str
) -> None:
    category_id = _category(api_client, alpha_token)
    key = uuid4().hex
    body = _expense_body(category_id, payment={"method": "cash", "reference": "REÇU-12"})

    created = api_client.post(EXPENSES, headers=write_headers(alpha_token, key), json=body)
    assert created.status_code == 201, created.text
    expense = created.json()
    assert expense["amount_paid"] == "75000.00"

    # Même clé, même corps : rejeu, ni seconde dépense ni second décaissement.
    replayed = api_client.post(EXPENSES, headers=write_headers(alpha_token, key), json=body)
    assert replayed.status_code == 201, replayed.text
    assert replayed.json()["id"] == expense["id"]

    payments = _payments_of_expense(api_client, alpha_token, expense["id"])
    assert [(p["amount"], p["method"], p["reference"]) for p in payments] == [
        ("75000.00", "cash", "REÇU-12")
    ]

    # Paiement annulé : la dépense redevient à régler.
    cancelled = api_client.post(
        f"/api/v1/payments/{payments[0]['id']}/cancel",
        headers=write_headers(alpha_token),
        json={"reason": "Saisie en double sur la caisse"},
    )
    assert cancelled.status_code == 201, cancelled.text
    detail = api_client.get(f"{EXPENSES}/{expense['id']}", headers=auth_headers(alpha_token))
    assert detail.json()["amount_paid"] == "0.00"


def test_an_expense_without_payment_is_unpaid(api_client: TestClient, alpha_token: str) -> None:
    category_id = _category(api_client, alpha_token)
    created = api_client.post(
        EXPENSES, headers=write_headers(alpha_token), json=_expense_body(category_id)
    )
    assert created.status_code == 201, created.text
    assert created.json()["amount_paid"] == "0.00"

    listed = api_client.get(
        f"{EXPENSES}?category_id={category_id}", headers=auth_headers(alpha_token)
    ).json()
    assert [item["amount_paid"] for item in listed["items"]] == ["0.00"]


def test_a_refused_payment_rolls_the_expense_back(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Sans `payments:create`, la dépense payée est refusée **entière**."""
    name = f"saisie-{uuid4().hex[:6]}"
    role = api_client.post(
        "/api/v1/roles",
        headers=auth_headers(alpha_token),
        json={"name": name, "permissions": ["expenses:create", "expenses:read"]},
    )
    assert role.status_code == 201, role.text
    token = create_user_with_role(
        api_client, alpha_token, company_alpha, role=name, email=f"{name}@societe-alpha.example.com"
    )

    category_id = _category(api_client, alpha_token)
    body = _expense_body(category_id, payment={"method": "cash"})
    refused = api_client.post(EXPENSES, headers=write_headers(token), json=body)
    assert refused.status_code == 403, refused.text

    listed = api_client.get(
        f"{EXPENSES}?category_id={category_id}", headers=auth_headers(alpha_token)
    ).json()
    assert listed["total"] == 0

    # Sans bloc de paiement, le même compte constate bien la charge.
    accepted = api_client.post(
        EXPENSES, headers=write_headers(token), json=_expense_body(category_id)
    )
    assert accepted.status_code == 201, accepted.text


# ------------------------------------------------------------------- journal


def test_the_activity_log_reads_both_channels_filtered(
    api_client: TestClient, alpha_token: str
) -> None:
    category_id = _category(api_client, alpha_token)
    expense = api_client.post(
        EXPENSES, headers=write_headers(alpha_token), json=_expense_body(category_id)
    ).json()

    logs = api_client.get(
        f"{AUDIT}?entity_table=expenses&entity_id={expense['id']}",
        headers=auth_headers(alpha_token),
    )
    assert logs.status_code == 200, logs.text
    page = logs.json()
    assert page["total"] == 1
    row = page["items"][0]
    assert row["action"] == "insert"
    assert row["actor_name"]
    assert row["diff"]["after"]["expense_no"] == expense["expense_no"]

    none = api_client.get(
        f"{AUDIT}?entity_table=expenses&entity_id={expense['id']}&action=delete",
        headers=auth_headers(alpha_token),
    ).json()
    assert none["total"] == 0

    bad = api_client.get(f"{AUDIT}?action=truncate", headers=auth_headers(alpha_token))
    assert bad.status_code == 422


def test_the_activity_log_is_for_manager_and_accountant(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    accountant = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="comptable",
        email=f"c-{uuid4().hex[:8]}@societe-alpha.example.com",
    )
    seller = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="vendeur",
        email=f"v-{uuid4().hex[:8]}@societe-alpha.example.com",
    )
    assert api_client.get(AUDIT, headers=auth_headers(accountant)).status_code == 200
    assert api_client.get(AUDIT, headers=auth_headers(seller)).status_code == 403
    # Paramètres : le vendeur n'y a aucun accès côté serveur (e2e de la phase 13).
    assert api_client.get("/api/v1/users", headers=auth_headers(seller)).status_code == 403
    patched = api_client.patch(
        "/api/v1/companies/me", headers=auth_headers(seller), json={"name": "Piratée"}
    )
    assert patched.status_code == 403
