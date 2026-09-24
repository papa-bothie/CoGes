"""Créances, dettes fournisseurs et abandon de créance vus par l'API.

Ce que ces tests tiennent :

* une dette fournisseur se saisit à la main (ADR 0029) — aucune règle implicite ne
  la crée depuis une dépense ;
* une créance client reste soumise au plafond de crédit, qu'elle vienne d'une vente
  ou d'une saisie ;
* l'abandon est réservé au gérant, exige un motif, laisse `principal` intact, et
  n'émet **aucun** événement : `debt.settled` dirait qu'elle a été réglée.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests.conftest import (
    TEST_PASSWORD,
    DemoCompany,
    auth_headers,
    read_scalar_in_tenant,
    write_headers,
)

pytestmark = pytest.mark.integration


def _role_id(client: TestClient, token: str, name: str) -> str:
    response = client.get("/api/v1/roles?page_size=50", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return str(next(role["id"] for role in response.json()["items"] if role["name"] == name))


def _token_for_role(client: TestClient, token: str, company: DemoCompany, role: str) -> str:
    """Compte porteur d'un rôle système, et son jeton d'accès."""
    email = f"{role}-{uuid4().hex[:8]}@{company.slug}.example.com"
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


def _supplier(client: TestClient, token: str) -> str:
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/suppliers", headers=auth_headers(token), json={"name": f"Fournisseur {marker}"}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _customer(client: TestClient, token: str, *, credit_limit: str | None = None) -> str:
    marker = uuid4().hex[:8]
    payload: dict[str, Any] = {"name": f"Client {marker}"}
    if credit_limit is not None:
        payload["credit_limit"] = credit_limit
    created = client.post("/api/v1/customers", headers=auth_headers(token), json=payload)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def test_a_supplier_debt_is_entered_by_hand(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Fournisseur, montant, échéance : l'engagement est déclaré, pas déduit."""
    supplier_id = _supplier(api_client, alpha_token)

    created = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={
            "party_type": "supplier",
            "supplier_id": supplier_id,
            "principal": "150000.00",
            "due_date": "2026-12-31",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["party_type"] == "supplier"
    assert body["principal"] == "150000.00"
    assert body["balance"] == "150000.00"
    assert body["status"] == "open"
    assert body["allocations"] == []

    emitted = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM business_events "
        " WHERE event_type = 'debt.created' AND aggregate_id = :id",
        {"id": UUID(str(body["id"]))},
    )
    assert emitted == 1, "une dette ouverte s'annonce"


def test_a_debt_must_name_exactly_one_party(api_client: TestClient, alpha_token: str) -> None:
    """`debts_party_xor` est doublé dans le schéma : le refus nomme le champ."""
    supplier_id = _supplier(api_client, alpha_token)
    customer_id = _customer(api_client, alpha_token)

    both = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={
            "party_type": "supplier",
            "supplier_id": supplier_id,
            "customer_id": customer_id,
            "principal": "1000.00",
        },
    )
    assert both.status_code == 422, both.text

    neither = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={"party_type": "customer", "principal": "1000.00"},
    )
    assert neither.status_code == 422, neither.text


def test_a_hand_written_credit_respects_the_credit_limit(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le plafond ne dépend pas du chemin par lequel la dette arrive."""
    customer_id = _customer(api_client, alpha_token, credit_limit="1000.00")

    first = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={"party_type": "customer", "customer_id": customer_id, "principal": "800.00"},
    )
    assert first.status_code == 201, first.text

    second = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={"party_type": "customer", "customer_id": customer_id, "principal": "300.00"},
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "credit_limit_exceeded"
    details = second.json()["error"]["details"]
    assert details["outstanding"] == "800.00"
    assert details["credit_limit"] == "1000.00"


def test_debts_can_be_filtered_by_party_status_and_due_date(
    api_client: TestClient, alpha_token: str
) -> None:
    """Les trois questions du gérant : qui, où en est-on, et qu'est-ce qui traîne."""
    supplier_id = _supplier(api_client, alpha_token)
    overdue = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={
            "party_type": "supplier",
            "supplier_id": supplier_id,
            "principal": "1000.00",
            "due_date": "2020-01-01",
        },
    )
    assert overdue.status_code == 201, overdue.text
    overdue_id = str(overdue.json()["id"])

    listed = api_client.get(
        "/api/v1/debts?party_type=supplier&overdue=true&page_size=100",
        headers=auth_headers(alpha_token),
    )
    assert listed.status_code == 200, listed.text
    identifiers = [item["id"] for item in listed.json()["items"]]
    assert overdue_id in identifiers

    open_only = api_client.get(
        "/api/v1/debts?status=paid&page_size=100", headers=auth_headers(alpha_token)
    )
    assert open_only.status_code == 200
    assert overdue_id not in [item["id"] for item in open_only.json()["items"]]


def test_only_the_manager_writes_off_a_debt(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """`debts:write_off` n'est pas `debts:update` : le comptable ne renonce pas.

    Le comptable tient les écritures ; abandonner une créance est une renonciation
    à un actif, et le catalogue lui refuse ce droit (ADR 0029).
    """
    supplier_id = _supplier(api_client, alpha_token)
    debt_id = str(
        api_client.post(
            "/api/v1/debts",
            headers=write_headers(alpha_token),
            json={"party_type": "supplier", "supplier_id": supplier_id, "principal": "1000.00"},
        ).json()["id"]
    )
    accountant = _token_for_role(api_client, alpha_token, company_alpha, "comptable")

    refused = api_client.post(
        f"/api/v1/debts/{debt_id}/write-off",
        headers=auth_headers(accountant),
        json={"reason": "Client introuvable depuis six mois"},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["required_permission"] == "debts:write_off"


def test_writing_off_keeps_the_principal_and_logs_the_reason(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """La dette est close, pas effacée : `principal` reste lisible, le motif aussi."""
    customer_id = _customer(api_client, alpha_token)
    debt_id = str(
        api_client.post(
            "/api/v1/debts",
            headers=write_headers(alpha_token),
            json={"party_type": "customer", "customer_id": customer_id, "principal": "2500.00"},
        ).json()["id"]
    )

    reason = "Client parti sans laisser d'adresse, créance irrécouvrable"
    written_off = api_client.post(
        f"/api/v1/debts/{debt_id}/write-off",
        headers=auth_headers(alpha_token),
        json={"reason": reason},
    )
    assert written_off.status_code == 200, written_off.text
    body = written_off.json()
    assert body["status"] == "written_off"
    assert body["principal"] == "2500.00", "`principal` n'est jamais réécrit (§ 5.5)"
    assert body["closed_at"] is not None, "`debts_closed_coherent` exige une date"

    logged = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT diff -> 'after' ->> 'reason' FROM audit_logs "
        " WHERE entity_table = 'debts' AND entity_id = :id AND action = 'cancel'",
        {"id": UUID(debt_id)},
    )
    assert logged == reason

    emitted = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM business_events "
        " WHERE event_type = 'debt.settled' AND aggregate_id = :id",
        {"id": UUID(debt_id)},
    )
    assert emitted == 0, "un abandon n'est pas un règlement"


def test_a_written_off_debt_refuses_a_second_abandonment(
    api_client: TestClient, alpha_token: str
) -> None:
    """Deux fois abandonnée, c'est une fois de trop : 409, pas un silence."""
    supplier_id = _supplier(api_client, alpha_token)
    debt_id = str(
        api_client.post(
            "/api/v1/debts",
            headers=write_headers(alpha_token),
            json={"party_type": "supplier", "supplier_id": supplier_id, "principal": "1000.00"},
        ).json()["id"]
    )
    reason = "Fournisseur disparu, engagement sans objet"

    first = api_client.post(
        f"/api/v1/debts/{debt_id}/write-off",
        headers=auth_headers(alpha_token),
        json={"reason": reason},
    )
    assert first.status_code == 200, first.text

    second = api_client.post(
        f"/api/v1/debts/{debt_id}/write-off",
        headers=auth_headers(alpha_token),
        json={"reason": reason},
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "debt_already_closed"


def test_a_partially_paid_debt_can_still_be_written_off(
    api_client: TestClient,
    alpha_token: str,
    session_factory: sessionmaker[Any],
    company_alpha: DemoCompany,
) -> None:
    """Renoncer au reliquat est le cas réel, et il est autorisé (ADR 0029).

    C'est la différence avec l'annulation d'une vente, qui refuse une dette déjà
    réglée en partie : là, de l'argent reçu devrait d'abord être rendu. Ici, on
    renonce à ce qui n'a jamais été perçu.
    """
    customer_id = _customer(api_client, alpha_token)
    debt_id = str(
        api_client.post(
            "/api/v1/debts",
            headers=write_headers(alpha_token),
            json={"party_type": "customer", "customer_id": customer_id, "principal": "1000.00"},
        ).json()["id"]
    )
    paid = api_client.post(
        "/api/v1/payments",
        headers=write_headers(alpha_token),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": "400.00",
            "allocations": [{"debt_id": debt_id, "amount": "400.00"}],
        },
    )
    assert paid.status_code == 201, paid.text

    written_off = api_client.post(
        f"/api/v1/debts/{debt_id}/write-off",
        headers=auth_headers(alpha_token),
        json={"reason": "Reliquat abandonné, client insolvable"},
    )
    assert written_off.status_code == 200, written_off.text
    assert written_off.json()["amount_paid"] == "400.00"
    assert written_off.json()["balance"] == "600.00"

    status = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT status FROM debts WHERE id = :id",
        {"id": UUID(debt_id)},
    )
    assert status == "written_off"


def test_an_open_debt_is_never_reported_as_settled(
    api_client: TestClient, alpha_token: str
) -> None:
    """Une dette abandonnée sort des encours : `pa_rollup` ne la touche plus."""
    supplier_id = _supplier(api_client, alpha_token)
    debt_id = str(
        api_client.post(
            "/api/v1/debts",
            headers=write_headers(alpha_token),
            json={"party_type": "supplier", "supplier_id": supplier_id, "principal": "1000.00"},
        ).json()["id"]
    )
    api_client.post(
        f"/api/v1/debts/{debt_id}/write-off",
        headers=auth_headers(alpha_token),
        json={"reason": "Engagement annulé par le fournisseur lui-même"},
    )

    refused = api_client.post(
        "/api/v1/payments",
        headers=write_headers(alpha_token),
        json={
            "direction": "outflow",
            "method": "cash",
            "amount": "100.00",
            "allocations": [{"debt_id": debt_id, "amount": "100.00"}],
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "debt_already_closed"


def test_the_detail_of_a_debt_shows_what_paid_it(api_client: TestClient, alpha_token: str) -> None:
    """Le détail rend les lettrages : on voit *par quoi* le solde a baissé."""
    customer_id = _customer(api_client, alpha_token)
    debt_id = str(
        api_client.post(
            "/api/v1/debts",
            headers=write_headers(alpha_token),
            json={"party_type": "customer", "customer_id": customer_id, "principal": "900.00"},
        ).json()["id"]
    )
    api_client.post(
        "/api/v1/payments",
        headers=write_headers(alpha_token),
        json={
            "direction": "inflow",
            "method": "mobile_money",
            "amount": "300.00",
            "allocations": [{"debt_id": debt_id, "amount": "300.00"}],
        },
    )

    detail = api_client.get(f"/api/v1/debts/{debt_id}", headers=auth_headers(alpha_token))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["amount_paid"] == "300.00"
    assert body["balance"] == "600.00"
    assert body["status"] == "partially_paid"
    assert len(body["allocations"]) == 1
    assert Decimal(body["allocations"][0]["amount"]) == Decimal("300.00")
