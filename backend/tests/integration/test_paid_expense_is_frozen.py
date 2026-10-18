"""Une dépense déjà payée ne change plus de montant et ne se supprime pas (P2.10, ADR 0088).

Le décaissement restait en caisse, rattaché à une dépense dont le montant avait changé
— ou qui n'existait plus : la caisse ne s'expliquait plus. Choix du propriétaire :
refuser (409). Pour corriger, on annule d'abord le paiement par contre-écriture
(ADR 0038), puis on modifie.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, write_headers
from tests.integration.test_expenses_api import EXPENSES, _category, _expense

pytestmark = pytest.mark.integration


def _paid_expense(client: TestClient, token: str) -> dict[str, Any]:
    return _expense(client, token, _category(client, token), payment={"method": "cash"})


def test_the_amount_of_a_paid_expense_cannot_change(
    api_client: TestClient, alpha_token: str
) -> None:
    expense = _paid_expense(api_client, alpha_token)

    changed = api_client.patch(
        f"{EXPENSES}/{expense['id']}", headers=auth_headers(alpha_token), json={"amount": "1.00"}
    )

    assert changed.status_code == 409, changed.text
    assert changed.json()["error"]["code"] == "expense_paid"


def test_a_paid_expense_cannot_be_deleted(api_client: TestClient, alpha_token: str) -> None:
    expense = _paid_expense(api_client, alpha_token)

    deleted = api_client.delete(f"{EXPENSES}/{expense['id']}", headers=auth_headers(alpha_token))

    assert deleted.status_code == 409, deleted.text


def test_the_label_of_a_paid_expense_can_still_be_fixed(
    api_client: TestClient, alpha_token: str
) -> None:
    expense = _paid_expense(api_client, alpha_token)
    changed = api_client.patch(
        f"{EXPENSES}/{expense['id']}",
        headers=auth_headers(alpha_token),
        json={"label": "Loyer d'octobre"},
    )
    assert changed.status_code == 200, changed.text


def test_once_the_payment_is_cancelled_the_expense_can_change(
    api_client: TestClient, alpha_token: str
) -> None:
    expense = _paid_expense(api_client, alpha_token)
    payments = api_client.get(
        "/api/v1/payments", headers=auth_headers(alpha_token), params={"expense_id": expense["id"]}
    ).json()["items"]
    payment = next(item for item in payments if item["expense_id"] == expense["id"])
    cancelled = api_client.post(
        f"/api/v1/payments/{payment['id']}/cancel",
        headers=write_headers(alpha_token),
        json={"reason": "Mauvais montant"},
    )
    assert cancelled.status_code in (200, 201), cancelled.text

    changed = api_client.patch(
        f"{EXPENSES}/{expense['id']}", headers=auth_headers(alpha_token), json={"amount": "1.00"}
    )
    assert changed.status_code == 200, changed.text
