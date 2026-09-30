"""Enrichissements de lecture servis au frontend (ADR 0050).

Aucun de ces champs ne porte une règle : ce sont des libellés et des cumuls que le
front aurait sinon reconstitués ligne par ligne. Les tests vérifient qu'ils disent
vrai, et que les nouveaux filtres ne laissent rien passer d'une autre entreprise.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, write_headers

pytestmark = pytest.mark.integration


def _product(client: TestClient, token: str, *, stock: str | None = "50") -> dict[str, Any]:
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"sku": f"ENR-{marker}", "name": f"Article {marker}", "unit_price": "1000.00"},
    )
    assert created.status_code == 201, created.text
    product: dict[str, Any] = created.json()
    if stock is not None:
        stocked = client.post(
            "/api/v1/inventory/movements",
            headers=auth_headers(token),
            json={
                "product_id": product["id"],
                "type": "initial",
                "qty_delta": stock,
                "unit_cost": "600",
            },
        )
        assert stocked.status_code == 201, stocked.text
    return product


def _customer(client: TestClient, token: str) -> dict[str, Any]:
    created = client.post(
        "/api/v1/customers",
        headers=auth_headers(token),
        json={"name": f"Client {uuid4().hex[:8]}", "credit_limit": "100000"},
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def _draft(client: TestClient, token: str, customer_id: str | None = None) -> str:
    payload = {} if customer_id is None else {"customer_id": customer_id}
    sale = client.post("/api/v1/sales", headers=auth_headers(token), json=payload)
    assert sale.status_code == 201, sale.text
    return str(sale.json()["id"])


def test_sale_lines_carry_the_product_labels(api_client: TestClient, alpha_token: str) -> None:
    product = _product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)

    added = api_client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(alpha_token),
        json={"product_id": product["id"], "qty": "2"},
    )
    assert added.status_code == 201, added.text
    assert added.json()["product_name"] == product["name"]
    assert added.json()["sku"] == product["sku"]
    assert added.json()["returned_qty"] == "0.000"

    updated = api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{added.json()['id']}",
        headers=auth_headers(alpha_token),
        json={"qty": "3"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["product_name"] == product["name"]

    detail = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token)).json()
    assert detail["items"][0]["sku"] == product["sku"]


def test_returned_qty_accumulates_across_returns(api_client: TestClient, alpha_token: str) -> None:
    product = _product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)
    item = api_client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(alpha_token),
        json={"product_id": product["id"], "qty": "5"},
    ).json()
    total = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token)).json()[
        "total"
    ]
    confirmed = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(alpha_token),
        json={"paid_amount": total, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    for qty in ("1", "2"):
        returned = api_client.post(
            f"/api/v1/sales/{sale_id}/returns",
            headers=write_headers(alpha_token),
            json={"lines": [{"sale_item_id": item["id"], "qty": qty}]},
        )
        assert returned.status_code == 201, returned.text

    detail = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token)).json()
    assert detail["items"][0]["returned_qty"] == "3.000"


def test_the_sale_list_names_the_customer(api_client: TestClient, alpha_token: str) -> None:
    customer = _customer(api_client, alpha_token)
    named = _draft(api_client, alpha_token, customer["id"])
    anonymous = _draft(api_client, alpha_token)

    listed = api_client.get(
        f"/api/v1/sales?customer_id={customer['id']}", headers=auth_headers(alpha_token)
    ).json()
    assert [(sale["id"], sale["customer_name"]) for sale in listed["items"]] == [
        (named, customer["name"])
    ]

    detail = api_client.get(f"/api/v1/sales/{anonymous}", headers=auth_headers(alpha_token))
    assert detail.json()["customer_name"] is None


def test_the_stock_view_reads_a_batch_of_products(api_client: TestClient, alpha_token: str) -> None:
    first = _product(api_client, alpha_token, stock="5")
    second = _product(api_client, alpha_token, stock="7")
    unstocked = _product(api_client, alpha_token, stock=None)

    query = "&".join(f"product_id={p['id']}" for p in (first, second, unstocked))
    response = api_client.get(f"/api/v1/inventory/stock?{query}", headers=auth_headers(alpha_token))
    assert response.status_code == 200, response.text
    body = response.json()
    # Un article sans mouvement n'a pas de ligne : rien n'est inventé.
    assert body["total"] == 2
    assert {line["product_id"]: line["qty_on_hand"] for line in body["items"]} == {
        first["id"]: "5.000",
        second["id"]: "7.000",
    }


def test_the_stock_view_caps_the_batch(api_client: TestClient, alpha_token: str) -> None:
    query = "&".join(f"product_id={uuid4()}" for _ in range(101))
    response = api_client.get(f"/api/v1/inventory/stock?{query}", headers=auth_headers(alpha_token))
    assert response.status_code == 422


def test_debts_can_be_filtered_by_customer(api_client: TestClient, alpha_token: str) -> None:
    product = _product(api_client, alpha_token)
    customer = _customer(api_client, alpha_token)
    other = _customer(api_client, alpha_token)
    for owner in (customer, other):
        sale_id = _draft(api_client, alpha_token, owner["id"])
        api_client.post(
            f"/api/v1/sales/{sale_id}/items",
            headers=auth_headers(alpha_token),
            json={"product_id": product["id"], "qty": "1"},
        )
        confirmed = api_client.post(
            f"/api/v1/sales/{sale_id}/confirm",
            headers=write_headers(alpha_token),
            json={"paid_amount": "0", "method": "cash"},
        )
        assert confirmed.status_code == 200, confirmed.text

    listed = api_client.get(
        f"/api/v1/debts?customer_id={customer['id']}", headers=auth_headers(alpha_token)
    ).json()
    assert listed["total"] == 1
    assert listed["items"][0]["customer_id"] == customer["id"]


def test_search_puts_the_exact_match_first(api_client: TestClient, alpha_token: str) -> None:
    """Vingt noms voisins triés par nom ne doivent pas repousser le bon hors de la page."""
    family = f"Rang {uuid4().hex[:6]}"
    for index in range(12):
        created = api_client.post(
            "/api/v1/products",
            headers=auth_headers(alpha_token),
            json={
                "sku": f"RG-{uuid4().hex[:8]}",
                "name": f"{family} A{index:02d}",
                "unit_price": "10",
            },
        )
        assert created.status_code == 201, created.text
    target = api_client.post(
        "/api/v1/products",
        headers=auth_headers(alpha_token),
        json={"sku": f"RG-{uuid4().hex[:8]}", "name": f"{family} Z", "unit_price": "10"},
    ).json()

    found = api_client.get(
        "/api/v1/products",
        headers=auth_headers(alpha_token),
        params={"search": target["name"], "page_size": 5},
    ).json()
    assert found["items"][0]["id"] == target["id"]

    by_sku = api_client.get(
        "/api/v1/products",
        headers=auth_headers(alpha_token),
        params={"search": target["sku"], "page_size": 5},
    ).json()
    assert by_sku["items"][0]["id"] == target["id"]
