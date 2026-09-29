"""Les filtres de lecture ajoutés pour le frontend (ADR 0050) ne franchissent pas le tenant.

Un identifiant d'une autre entreprise passé en filtre ne doit rien révéler : la
réponse est vide, exactement comme pour un identifiant qui n'existe nulle part.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, write_headers

pytestmark = pytest.mark.tenancy


def _stocked_product(client: TestClient, token: str) -> str:
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"sku": f"XT-{marker}", "name": f"Article {marker}", "unit_price": "500.00"},
    )
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    stocked = client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={"product_id": product_id, "type": "initial", "qty_delta": "10", "unit_cost": "300"},
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def _customer_with_debt(client: TestClient, token: str, product_id: str) -> str:
    customer = client.post(
        "/api/v1/customers",
        headers=auth_headers(token),
        json={"name": f"Client {uuid4().hex[:8]}", "credit_limit": "100000"},
    )
    assert customer.status_code == 201, customer.text
    customer_id = str(customer.json()["id"])
    sale: dict[str, Any] = client.post(
        "/api/v1/sales", headers=auth_headers(token), json={"customer_id": customer_id}
    ).json()
    client.post(
        f"/api/v1/sales/{sale['id']}/items",
        headers=auth_headers(token),
        json={"product_id": product_id, "qty": "1"},
    )
    confirmed = client.post(
        f"/api/v1/sales/{sale['id']}/confirm",
        headers=write_headers(token),
        json={"paid_amount": "0", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return customer_id


def test_the_stock_filter_ignores_a_foreign_product(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    foreign = _stocked_product(api_client, beta_token)

    seen_by_alpha = api_client.get(
        f"/api/v1/inventory/stock?product_id={foreign}", headers=auth_headers(alpha_token)
    )
    assert seen_by_alpha.status_code == 200
    assert seen_by_alpha.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}

    # Le propriétaire, lui, voit bien sa ligne : le test ne passe pas à vide.
    seen_by_beta = api_client.get(
        f"/api/v1/inventory/stock?product_id={foreign}", headers=auth_headers(beta_token)
    )
    assert seen_by_beta.json()["total"] == 1


def test_the_debt_filter_ignores_a_foreign_customer(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    foreign = _customer_with_debt(api_client, beta_token, _stocked_product(api_client, beta_token))

    seen_by_alpha = api_client.get(
        f"/api/v1/debts?customer_id={foreign}", headers=auth_headers(alpha_token)
    )
    assert seen_by_alpha.status_code == 200
    assert seen_by_alpha.json()["total"] == 0

    seen_by_beta = api_client.get(
        f"/api/v1/debts?customer_id={foreign}", headers=auth_headers(beta_token)
    )
    assert seen_by_beta.json()["total"] == 1
