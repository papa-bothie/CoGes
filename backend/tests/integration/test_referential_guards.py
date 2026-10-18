"""Référentiels : ce qu'un article ou un client ne peut plus perdre (P2.11, P2.12 ; ADR 0088).

P2.11
* `is_stock_tracked` changé sur un article qui a déjà des mouvements : son journal et sa
  projection ne se correspondaient plus (des mouvements sur un article « non suivi »,
  ou un article suivi sans stock d'ouverture) ;
* un article supprimé alors qu'il reste du stock : une valeur de stock invisible ;
* un retour sur un article supprimé doit quand même remettre la marchandise en stock ;
* un client supprimé avec des dettes ouvertes : des créances sans débiteur visible.

P2.12
* `{"name": null}` sur une mise à jour : `setattr(None)` sur une colonne NOT NULL, 500.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, write_headers
from tests.integration.test_returns_api import _confirmed_sale, _create_return, _stock_of
from tests.integration.test_returns_api import _product as _sold_product

pytestmark = pytest.mark.integration


def _product(client: TestClient, token: str, *, stock: str | None = "5") -> str:
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"name": f"Garde {uuid4().hex[:6]}", "unit_price": "1000.00", "default_tax_rate": "0"},
    )
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    if stock is not None:
        moved = client.post(
            "/api/v1/inventory/movements",
            headers=auth_headers(token),
            json={
                "product_id": product_id,
                "type": "initial",
                "qty_delta": stock,
                "unit_cost": "500",
            },
        )
        assert moved.status_code == 201, moved.text
    return product_id


def test_stock_tracking_is_frozen_once_the_product_has_movements(
    api_client: TestClient, alpha_token: str
) -> None:
    product_id = _product(api_client, alpha_token)

    changed = api_client.patch(
        f"/api/v1/products/{product_id}",
        headers=auth_headers(alpha_token),
        json={"is_stock_tracked": False},
    )

    assert changed.status_code == 409, changed.text
    assert changed.json()["error"]["code"] == "stock_tracking_locked"


def test_stock_tracking_may_change_before_any_movement(
    api_client: TestClient, alpha_token: str
) -> None:
    product_id = _product(api_client, alpha_token, stock=None)
    changed = api_client.patch(
        f"/api/v1/products/{product_id}",
        headers=auth_headers(alpha_token),
        json={"is_stock_tracked": False},
    )
    assert changed.status_code == 200, changed.text


def test_a_product_with_stock_left_cannot_be_deleted(
    api_client: TestClient, alpha_token: str
) -> None:
    product_id = _product(api_client, alpha_token)

    deleted = api_client.delete(f"/api/v1/products/{product_id}", headers=auth_headers(alpha_token))

    assert deleted.status_code == 409, deleted.text
    assert deleted.json()["error"]["code"] == "product_has_stock"


def test_a_return_on_a_deleted_product_puts_the_goods_back(
    api_client: TestClient, alpha_token: str
) -> None:
    """Vendu jusqu'au dernier, supprimé, puis rapporté : il rentre en stock."""
    product_id = _sold_product(api_client, alpha_token)
    stock = _stock_of(api_client, alpha_token, product_id)["qty_on_hand"]
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty=stock)
    deleted = api_client.delete(f"/api/v1/products/{product_id}", headers=auth_headers(alpha_token))
    assert deleted.status_code == 200, deleted.text

    returned = _create_return(api_client, alpha_token, sale_id, item_id, "1")

    assert returned.status_code == 201, returned.text
    detail = api_client.get(
        "/api/v1/inventory/movements",
        headers=auth_headers(alpha_token),
        params={"product_id": product_id},
    )
    kinds = [movement["type"] for movement in detail.json()["items"]]
    assert "customer_return_in" in kinds, f"aucune remise en stock : {kinds}"


def test_a_customer_with_open_debts_cannot_be_deleted(
    api_client: TestClient, alpha_token: str
) -> None:
    customer = api_client.post(
        "/api/v1/customers", headers=auth_headers(alpha_token), json={"name": "Doit encore"}
    ).json()
    debt = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={"party_type": "customer", "customer_id": customer["id"], "principal": "5000.00"},
    )
    assert debt.status_code == 201, debt.text

    deleted = api_client.delete(
        f"/api/v1/customers/{customer['id']}", headers=auth_headers(alpha_token)
    )

    assert deleted.status_code == 409, deleted.text
    assert deleted.json()["error"]["code"] == "customer_has_open_debts"


@pytest.mark.parametrize(
    ("create", "update_path", "field"),
    [
        (("/api/v1/customers", {"name": "Nul"}), "/api/v1/customers/{id}", "name"),
        (("/api/v1/suppliers", {"name": "Nul"}), "/api/v1/suppliers/{id}", "name"),
        (("/api/v1/categories", {"name": "Nul"}), "/api/v1/categories/{id}", "name"),
        (
            ("/api/v1/products", {"name": "Nul", "unit_price": "1000.00", "default_tax_rate": "0"}),
            "/api/v1/products/{id}",
            "name",
        ),
        (
            ("/api/v1/products", {"name": "Nul", "unit_price": "1000.00", "default_tax_rate": "0"}),
            "/api/v1/products/{id}",
            "unit",
        ),
        (
            ("/api/v1/products", {"name": "Nul", "unit_price": "1000.00", "default_tax_rate": "0"}),
            "/api/v1/products/{id}",
            "is_active",
        ),
    ],
)
def test_null_on_a_required_field_is_a_422(
    api_client: TestClient,
    alpha_token: str,
    create: tuple[str, dict[str, Any]],
    update_path: str,
    field: str,
) -> None:
    path, body = create
    body = {**body, "name": f"{body['name']} {uuid4().hex[:6]}"}
    created = api_client.post(path, headers=auth_headers(alpha_token), json=body)
    assert created.status_code == 201, created.text

    patched = api_client.patch(
        update_path.format(id=created.json()["id"]),
        headers=auth_headers(alpha_token),
        json={field: None},
    )

    assert patched.status_code == 422, patched.text
