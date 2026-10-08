"""Créer un article avec ce qu'on en a déjà (ADR 0066).

« Combien en avez-vous ? » fait partie du formulaire de création : l'article et son
mouvement `initial` naissent dans la même transaction, par `POST /inventory/products`
(Inventory compose la façade de Products, jamais l'inverse).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DemoCompany, auth_headers, create_user_with_role

pytestmark = pytest.mark.integration

NEW_PRODUCT = "/api/v1/inventory/products"


def _payload(**fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": f"Riz {uuid4().hex[:6]}",
        "unit": "sac",
        "unit_price": "15500",
        "cost_price": "14000",
        "opening_qty": "12",
        "reorder_point": "3",
    }
    payload.update(fields)
    return payload


def _stock(client: TestClient, token: str, product_id: str) -> list[dict[str, Any]]:
    response = client.get(
        f"/api/v1/inventory/stock?product_id={product_id}", headers=auth_headers(token)
    )
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def test_the_product_is_born_with_its_stock(api_client: TestClient, alpha_token: str) -> None:
    response = api_client.post(NEW_PRODUCT, headers=auth_headers(alpha_token), json=_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    product = body["product"]
    assert product["sku"].startswith("ART-")
    assert product["unit"] == "sac"
    assert product["reorder_point"] == "3.000"
    assert body["opening_movement"]["type"] == "initial"
    assert body["opening_movement"]["unit_cost"] == "14000.0000"

    [line] = _stock(api_client, alpha_token, product["id"])
    assert line["qty_on_hand"] == "12.000"


def test_without_quantity_no_movement_is_written(api_client: TestClient, alpha_token: str) -> None:
    response = api_client.post(
        NEW_PRODUCT, headers=auth_headers(alpha_token), json=_payload(opening_qty="0")
    )
    assert response.status_code == 201, response.text
    assert response.json()["opening_movement"] is None
    assert _stock(api_client, alpha_token, response.json()["product"]["id"]) == []


def test_a_quantity_needs_a_purchase_price(api_client: TestClient, alpha_token: str) -> None:
    """Le stock d'ouverture se valorise au prix d'achat : sans lui, pas de CMP."""
    response = api_client.post(
        NEW_PRODUCT, headers=auth_headers(alpha_token), json=_payload(cost_price=None)
    )
    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert any("prix d'achat" in field["message"] for field in fields), fields


def test_nothing_is_created_when_the_product_is_refused(
    api_client: TestClient, alpha_token: str
) -> None:
    """Un code-barres déjà pris : ni article, ni mouvement."""
    barcode = f"6{uuid4().int % 10**12:012d}"
    first = api_client.post(
        NEW_PRODUCT, headers=auth_headers(alpha_token), json=_payload(barcode=barcode)
    )
    assert first.status_code == 201, first.text
    name = f"Doublon {uuid4().hex[:6]}"
    second = api_client.post(
        NEW_PRODUCT, headers=auth_headers(alpha_token), json=_payload(barcode=barcode, name=name)
    )
    assert second.status_code == 409
    found = api_client.get(
        f"/api/v1/products?search={name}", headers=auth_headers(alpha_token)
    ).json()
    assert found["total"] == 0


def test_a_category_of_another_company_is_not_found(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    category = api_client.post(
        "/api/v1/categories",
        headers=auth_headers(beta_token),
        json={"name": f"Rayon {uuid4().hex[:6]}"},
    )
    assert category.status_code == 201, category.text
    response = api_client.post(
        NEW_PRODUCT,
        headers=auth_headers(alpha_token),
        json=_payload(category_id=category.json()["id"]),
    )
    assert response.status_code == 404


def test_a_salesperson_cannot_create_a_product(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    salesperson = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="vendeur",
        email=f"vendeur-{uuid4().hex[:8]}@societe-alpha.example.com",
    )
    response = api_client.post(NEW_PRODUCT, headers=auth_headers(salesperson), json=_payload())
    assert response.status_code == 403


def test_the_stock_line_carries_the_unit(api_client: TestClient, alpha_token: str) -> None:
    """« Plus que 2 sacs » : l'écran de correction lit l'unité sur la ligne de stock."""
    response = api_client.post(NEW_PRODUCT, headers=auth_headers(alpha_token), json=_payload())
    [line] = _stock(api_client, alpha_token, response.json()["product"]["id"])
    assert line["unit"] == "sac"
