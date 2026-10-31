"""Retrouver un article par son code-barres, pour l'entrée de stock par scan (prompt 33).

`GET /api/v1/inventory/products/by-barcode/{code}` (ADR 0106) : correspondance **exacte**
dans l'entreprise, articles vivants seulement, droit `inventory:read`. La réponse dit ce
que l'écran de livraison affiche : stock, coût moyen, dernier coût d'achat, prix de vente.
"""

from __future__ import annotations

import random
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.codes import ean13_check_digit
from tests.conftest import (
    DemoCompany,
    auth_headers,
    create_user_with_role,
    login_token,
    write_headers,
)

pytestmark = pytest.mark.integration

LOOKUP = "/api/v1/inventory/products/by-barcode"


def _ean13(first: str = "3") -> str:
    body = first + "".join(random.choices("0123456789", k=11))
    return body + ean13_check_digit(body)


def _create(
    client: TestClient, token: str, *, barcode: str, opening: str = "0", **fields: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"Riz {uuid4().hex[:6]}",
        "unit": "sac",
        "barcode": barcode,
        "unit_price": "15500",
        "cost_price": "100",
        "opening_qty": opening,
    }
    body.update(fields)
    response = client.post("/api/v1/inventory/products", headers=auth_headers(token), json=body)
    assert response.status_code == 201, response.text
    product: dict[str, Any] = response.json()["product"]
    return product


def _lookup(client: TestClient, token: str, code: str) -> Any:
    return client.get(f"{LOOKUP}/{code}", headers=auth_headers(token))


def test_a_known_code_gives_what_the_delivery_screen_shows(
    api_client: TestClient, alpha_token: str
) -> None:
    category = api_client.post(
        "/api/v1/categories", headers=auth_headers(alpha_token), json={"name": uuid4().hex[:8]}
    ).json()
    barcode = _ean13()
    product = _create(
        api_client, alpha_token, barcode=barcode, opening="5", category_id=category["id"]
    )

    response = _lookup(api_client, alpha_token, barcode)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["product_id"] == product["id"]
    assert body["name"] == product["name"]
    assert body["barcode"] == barcode
    assert body["category_name"] == category["name"]
    assert body["unit"] == "sac"
    assert body["is_stock_tracked"] is True
    assert body["qty_on_hand"] == "5.000"
    assert body["avg_cost"] == "100.0000"
    assert body["last_purchase_cost"] == "100.0000"
    assert body["unit_price"] == "15500.00"


def test_after_a_delivery_the_average_cost_is_recomputed_not_overwritten(
    api_client: TestClient, alpha_token: str
) -> None:
    """5 à 100 F puis 20 à 120 F : coût moyen 116 F, dernier coût 120 F (prompt 33, S2)."""
    barcode = _ean13()
    product = _create(api_client, alpha_token, barcode=barcode, opening="5")
    supplier = api_client.post(
        "/api/v1/suppliers", headers=auth_headers(alpha_token), json={"name": "Grossiste"}
    ).json()
    delivered = api_client.post(
        "/api/v1/inventory/deliveries",
        headers=write_headers(alpha_token),
        json={
            "supplier_id": supplier["id"],
            "payment_mode": "now",
            "method": "cash",
            "lines": [{"product_id": product["id"], "qty": "20", "unit_cost": "120"}],
        },
    )
    assert delivered.status_code == 201, delivered.text

    body = _lookup(api_client, alpha_token, barcode).json()
    assert body["qty_on_hand"] == "25.000"
    assert body["avg_cost"] == "116.0000"
    assert body["last_purchase_cost"] == "120.0000"
    # Le prix d'achat de la fiche ne change pas : la livraison a son propre coût.
    price = api_client.get(
        f"/api/v1/products/{product['id']}", headers=auth_headers(alpha_token)
    ).json()
    assert price["cost_price"] == "100.0000"


def test_a_product_without_stock_yet_answers_zero(api_client: TestClient, alpha_token: str) -> None:
    barcode = _ean13()
    _create(api_client, alpha_token, barcode=barcode)
    body = _lookup(api_client, alpha_token, barcode).json()
    assert body["qty_on_hand"] == "0.000"
    assert body["last_purchase_cost"] is None


def test_an_unknown_code_is_not_found(api_client: TestClient, alpha_token: str) -> None:
    response = _lookup(api_client, alpha_token, _ean13())
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "product_not_found"
    assert error["details"]["deleted_product"] is False


def test_a_deleted_product_is_named_as_such(api_client: TestClient, alpha_token: str) -> None:
    barcode = _ean13()
    product = _create(api_client, alpha_token, barcode=barcode)
    deleted = api_client.delete(
        f"/api/v1/products/{product['id']}", headers=auth_headers(alpha_token)
    )
    assert deleted.status_code == 200, deleted.text

    response = _lookup(api_client, alpha_token, barcode)
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "product_not_found"
    assert error["details"]["deleted_product"] is True


def test_an_untracked_product_is_returned_as_untracked(
    api_client: TestClient, alpha_token: str
) -> None:
    barcode = _ean13()
    _create(api_client, alpha_token, barcode=barcode, is_stock_tracked=False)
    body = _lookup(api_client, alpha_token, barcode).json()
    assert body["is_stock_tracked"] is False


def test_the_code_of_another_company_is_never_found(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    barcode = _ean13()
    _create(api_client, beta_token, barcode=barcode)
    response = _lookup(api_client, alpha_token, barcode)
    assert response.status_code == 404
    assert response.json()["error"]["details"]["deleted_product"] is False


def test_upc_a_and_ean_13_find_the_same_product(api_client: TestClient, alpha_token: str) -> None:
    ean = _ean13(first="0")
    product = _create(api_client, alpha_token, barcode=ean)
    assert _lookup(api_client, alpha_token, ean[1:]).json()["product_id"] == product["id"]

    upc = _ean13(first="0")[1:]
    other = _create(api_client, alpha_token, barcode=upc)
    assert _lookup(api_client, alpha_token, f"0{upc}").json()["product_id"] == other["id"]


def test_spaces_in_the_code_are_ignored(api_client: TestClient, alpha_token: str) -> None:
    barcode = _ean13()
    product = _create(api_client, alpha_token, barcode=barcode)
    spaced = f"{barcode[:4]}%20{barcode[4:]}"
    assert _lookup(api_client, alpha_token, spaced).json()["product_id"] == product["id"]


def test_a_wrong_check_digit_is_a_clear_422(api_client: TestClient, alpha_token: str) -> None:
    barcode = _ean13()
    wrong = barcode[:-1] + str((int(barcode[-1]) + 1) % 10)
    response = _lookup(api_client, alpha_token, wrong)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_barcode"
    assert "code-barres" in error["message"]


def test_the_salesperson_may_scan(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Le vendeur voit le stock en lecture (ADR 0099) : il peut retrouver un article."""
    barcode = _ean13()
    _create(api_client, alpha_token, barcode=barcode)
    seller = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="vendeur",
        email=f"vendeur-scan-{uuid4().hex[:6]}@example.com",
    )
    assert _lookup(api_client, seller, barcode).status_code == 200


def test_without_inventory_read_the_scan_is_refused(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    role = api_client.post(
        "/api/v1/roles",
        headers=auth_headers(alpha_token),
        json={"name": f"Caisse {uuid4().hex[:6]}", "permissions": ["products:read"]},
    )
    assert role.status_code == 201, role.text
    email = f"sans-stock-{uuid4().hex[:6]}@example.com"
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(alpha_token),
        json={
            "email": email,
            "full_name": "Sans stock",
            "password": "mot-de-passe-de-test-01",
            "role_ids": [role.json()["id"]],
        },
    )
    assert created.status_code == 201, created.text
    company = DemoCompany(
        company_id=company_alpha.company_id,
        manager_id=company_alpha.manager_id,
        slug=company_alpha.slug,
        email=email,
    )
    token = login_token(api_client, company, password="mot-de-passe-de-test-01")
    assert _lookup(api_client, token, _ean13()).status_code == 403
