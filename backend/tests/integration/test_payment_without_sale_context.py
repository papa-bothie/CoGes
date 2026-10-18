"""Un paiement saisi ne se rattache plus à une vente (prompt 21, P1.3 ; ADR 0087).

`PaymentCreate` acceptait `sale_id` et le recopiait sans rien vérifier : statut de la
vente, plafond, dette ouverte. Un porteur de `payments:create` pouvait faire monter
`paid_total` au-delà du total, ou encaisser en direct une vente dont la dette restait
ouverte — le client aurait payé deux fois. Le reste dû d'une vente suit sa dette
(ADR 0062) : on règle une vente en lettrant sa dette, jamais par `sale_id`.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant, write_headers
from tests.integration.test_payment_cancellation import _confirmed_sale, _customer

pytestmark = pytest.mark.integration

PAYMENTS = "/api/v1/payments"


def _pay_sale(client: TestClient, token: str, sale_id: str, amount: str) -> Any:
    return client.post(
        PAYMENTS,
        headers=write_headers(token),
        json={"direction": "inflow", "method": "cash", "amount": amount, "sale_id": sale_id},
    )


def _paid_total(session_factory: sessionmaker[Any], company: DemoCompany, sale_id: str) -> str:
    return str(
        read_scalar_in_tenant(
            session_factory,
            company.company_id,
            "SELECT paid_total FROM sales WHERE id = :id",
            {"id": sale_id},
        )
    )


def test_a_credit_sale_cannot_be_paid_around_its_debt(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """(1) Vente à crédit : un encaissement direct laisserait la dette ouverte."""
    sale = _confirmed_sale(
        api_client, alpha_token, paid="0", customer_id=_customer(api_client, alpha_token)
    )

    refused = _pay_sale(api_client, alpha_token, sale["id"], sale["total"])

    assert refused.status_code == 422, refused.text
    assert _paid_total(session_factory, company_alpha, sale["id"]) == "0.00"


def test_a_payment_cannot_push_a_sale_above_its_total(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """(2) Vente payée comptant : un second encaissement la ferait dépasser son total."""
    sale = _confirmed_sale(api_client, alpha_token)

    refused = _pay_sale(api_client, alpha_token, sale["id"], "1000.00")

    assert refused.status_code == 422, refused.text
    assert _paid_total(session_factory, company_alpha, sale["id"]) == sale["total"]


def test_a_draft_cannot_be_paid_directly(api_client: TestClient, alpha_token: str) -> None:
    """(3) Brouillon : rien n'est encore dû."""
    draft = api_client.post("/api/v1/sales", headers=auth_headers(alpha_token), json={})
    assert draft.status_code == 201, draft.text

    refused = _pay_sale(api_client, alpha_token, str(draft.json()["id"]), "500.00")

    assert refused.status_code == 422, refused.text


def test_the_legitimate_settlement_still_works(api_client: TestClient, alpha_token: str) -> None:
    """(4) Le geste de l'écran : un encaissement lettré sur la dette de la vente."""
    sale = _confirmed_sale(
        api_client, alpha_token, paid="0", customer_id=_customer(api_client, alpha_token)
    )

    paid = api_client.post(
        PAYMENTS,
        headers=write_headers(alpha_token),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": sale["total"],
            "allocations": [{"debt_id": sale["debt"]["id"], "amount": sale["total"]}],
        },
    )

    assert paid.status_code == 201, paid.text
    after = api_client.get(f"/api/v1/sales/{sale['id']}", headers=auth_headers(alpha_token))
    assert after.json()["balance"] == "0.00"


def test_an_unknown_sale_id_is_refused_too(api_client: TestClient, alpha_token: str) -> None:
    refused = _pay_sale(api_client, alpha_token, str(uuid4()), "500.00")
    assert refused.status_code == 422, refused.text
