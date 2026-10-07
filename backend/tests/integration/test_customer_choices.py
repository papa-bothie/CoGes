"""La liste des clients de « Nouvelle vente » (ADR 0063, bug B3 de la phase 15).

Une entreprise neuve par module : l'ordre attendu (récents, puis alphabétique) ne se
vérifie que si l'on connaît tous les clients de l'entreprise.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    write_headers,
)

pytestmark = pytest.mark.integration

CHOICES = "/api/v1/sales/customer-choices"


@pytest.fixture(scope="module")
def shop(app_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"choix-{uuid4().hex[:8]}")


@pytest.fixture
def token(api_client: TestClient, shop: DemoCompany) -> str:
    return login_token(api_client, shop)


def _customer(client: TestClient, token: str, name: str, phone: str | None = None) -> str:
    created = client.post(
        "/api/v1/customers", headers=auth_headers(token), json={"name": name, "phone": phone}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _product(client: TestClient, token: str) -> str:
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"sku": f"CH-{uuid4().hex[:8]}", "name": "Riz", "unit_price": "1000.00"},
    )
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    stocked = client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={"product_id": product_id, "type": "initial", "qty_delta": "100", "unit_cost": "600"},
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def _sell(client: TestClient, token: str, product_id: str, customer_id: str, paid: str) -> None:
    sale = client.post(
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
        json={"paid_amount": paid, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text


def _choices(client: TestClient, token: str, **params: Any) -> dict[str, Any]:
    response = client.get(CHOICES, headers=auth_headers(token), params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_recent_buyers_first_then_everyone_alphabetically(
    api_client: TestClient, token: str
) -> None:
    ids = {
        name: _customer(api_client, token, name, phone)
        for name, phone in [
            ("Awa Diop", "77 412 08 33"),
            ("Moussa Fall", "76 220 15 90"),
            ("Boutique Ndiaye", None),
            ("Ibrahima Ba", None),
        ]
    }
    product_id = _product(api_client, token)
    # Moussa achète à crédit, puis Ibrahima comptant : Ibrahima est le plus récent.
    _sell(api_client, token, product_id, ids["Moussa Fall"], paid="0")
    _sell(api_client, token, product_id, ids["Ibrahima Ba"], paid="1000.00")

    body = _choices(api_client, token)
    names = [item["name"] for item in body["items"]]
    assert names == ["Ibrahima Ba", "Moussa Fall", "Awa Diop", "Boutique Ndiaye"]
    assert [item["recent"] for item in body["items"]] == [True, True, False, False]
    assert body["total"] == 4

    by_name = {item["name"]: item for item in body["items"]}
    # Le prix est taxé au taux par défaut : on lit la dette telle qu'elle est.
    assert by_name["Moussa Fall"]["open_debt"] != "0.00"
    assert by_name["Ibrahima Ba"]["open_debt"] == "0.00"
    assert by_name["Awa Diop"]["phone"] == "77 412 08 33"


def test_pages_never_repeat_a_customer(api_client: TestClient, token: str) -> None:
    for index in range(7):
        _customer(api_client, token, f"Zz Page {index:02d}")

    first = _choices(api_client, token, page_size=3)
    seen = [item["id"] for item in first["items"]]
    page = 1
    while len(seen) < first["total"]:
        page += 1
        body = _choices(api_client, token, page=page, page_size=3)
        seen += [item["id"] for item in body["items"]]
        assert page < 20, "la pagination ne converge pas"

    assert len(seen) == len(set(seen)) == first["total"]


def test_a_search_ranks_by_relevance_without_the_recent_block(
    api_client: TestClient, token: str
) -> None:
    body = _choices(api_client, token, search="Moussa")
    assert [item["name"] for item in body["items"]][:1] == ["Moussa Fall"]
    assert all(item["recent"] is False for item in body["items"])
