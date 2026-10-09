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


def test_the_sale_customer_list_never_shows_another_company(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """`GET /sales/customer-choices` (ADR 0063) : ni en liste, ni en recherche, ni sa dette."""
    product_id = _stocked_product(api_client, beta_token)
    foreign = _customer_with_debt(api_client, beta_token, product_id)
    name = api_client.get(f"/api/v1/customers/{foreign}", headers=auth_headers(beta_token)).json()[
        "name"
    ]

    listed = api_client.get(
        "/api/v1/sales/customer-choices",
        headers=auth_headers(alpha_token),
        params={"page_size": 100},
    ).json()
    pages = [listed]
    for page in range(2, -(-listed["total"] // 100) + 1):
        pages.append(
            api_client.get(
                "/api/v1/sales/customer-choices",
                headers=auth_headers(alpha_token),
                params={"page_size": 100, "page": page},
            ).json()
        )
    assert foreign not in {item["id"] for body in pages for item in body["items"]}

    searched = api_client.get(
        "/api/v1/sales/customer-choices",
        headers=auth_headers(alpha_token),
        params={"search": name},
    ).json()
    assert foreign not in {item["id"] for item in searched["items"]}

    # Le propriétaire, lui, le voit avec sa dette : le test ne passe pas à vide.
    own = api_client.get(
        "/api/v1/sales/customer-choices",
        headers=auth_headers(beta_token),
        params={"search": name},
    ).json()
    mine = [item for item in own["items"] if item["id"] == foreign]
    assert mine and mine[0]["open_debt"] != "0.00"


def test_the_sales_search_by_name_never_finds_another_company(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """`GET /sales?search=` (ADR 0070) cherche les clients du tenant, jamais ceux d'autrui.

    Le nom est rare : la recherche par trigrammes trouverait sinon, chez alpha, ses
    propres clients au nom voisin (« Client … »), ce qui n'est pas une fuite.
    """
    product_id = _stocked_product(api_client, beta_token)
    name = f"Zéphyrine Kouyaté {uuid4().hex[:6]}"
    customer = api_client.post(
        "/api/v1/customers", headers=auth_headers(beta_token), json={"name": name}
    )
    assert customer.status_code == 201, customer.text
    sale: dict[str, Any] = api_client.post(
        "/api/v1/sales",
        headers=auth_headers(beta_token),
        json={"customer_id": customer.json()["id"]},
    ).json()
    api_client.post(
        f"/api/v1/sales/{sale['id']}/items",
        headers=auth_headers(beta_token),
        json={"product_id": product_id, "qty": "1"},
    )
    confirmed = api_client.post(
        f"/api/v1/sales/{sale['id']}/confirm",
        headers=write_headers(beta_token),
        json={"paid_amount": "500", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    seen_by_alpha = api_client.get(
        "/api/v1/sales", headers=auth_headers(alpha_token), params={"search": name}
    )
    assert seen_by_alpha.status_code == 200
    assert sale["id"] not in {item["id"] for item in seen_by_alpha.json()["items"]}

    seen_by_beta = api_client.get(
        "/api/v1/sales", headers=auth_headers(beta_token), params={"search": name}
    )
    assert sale["id"] in {item["id"] for item in seen_by_beta.json()["items"]}


def test_day_totals_count_only_the_readers_sales(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """`GET /sales/day-totals` (ADR 0070) : une vente de beta ne change rien chez alpha."""
    window = {"date_from": "2000-01-01T00:00:00Z", "date_to": "2100-01-01T00:00:00Z"}

    def counts(token: str) -> int:
        response = api_client.get(
            "/api/v1/sales/day-totals", headers=auth_headers(token), params=window
        )
        assert response.status_code == 200, response.text
        return sum(item["sale_count"] for item in response.json()["items"])

    alpha_before, beta_before = counts(alpha_token), counts(beta_token)
    _customer_with_debt(api_client, beta_token, _stocked_product(api_client, beta_token))
    assert counts(alpha_token) == alpha_before
    assert counts(beta_token) == beta_before + 1
