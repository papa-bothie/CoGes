"""Le reçu, source unique du ticket, de la facture et du PDF (prompt 35, bloc F, ADR 0112)."""

from __future__ import annotations

import io
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import auth_headers, write_headers

pytestmark = pytest.mark.integration


def _post(client: TestClient, token: str, path: str, body: Any) -> dict[str, Any]:
    response = client.post(path, headers=write_headers(token), json=body)
    assert response.status_code in (200, 201), f"{path} : {response.text}"
    return dict(response.json())


def _stocked(client: TestClient, token: str, **product: Any) -> str:
    body = {"name": f"Article {uuid4().hex[:8]}", "unit_price": "1500", **product}
    product_id = _post(client, token, "/api/v1/products", body)["id"]
    _post(
        client,
        token,
        "/api/v1/inventory/movements",
        {"product_id": product_id, "type": "initial", "qty_delta": "50", "unit_cost": "900"},
    )
    return product_id


def _confirmed_sale(
    client: TestClient,
    token: str,
    lines: list[dict[str, Any]],
    *,
    price: dict[str, str] | None = None,
) -> str:
    """Vente au comptoir payée comptant ; `price` change le prix de la première ligne."""
    sale_id = _post(client, token, "/api/v1/sales", {})["id"]
    items = [_post(client, token, f"/api/v1/sales/{sale_id}/items", line) for line in lines]
    if price is not None:
        changed = client.patch(
            f"/api/v1/sales/{sale_id}/items/{items[0]['id']}",
            headers=auth_headers(token),
            json=price,
        )
        assert changed.status_code == 200, changed.text
    total = client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(token)).json()["total"]
    _post(
        client,
        token,
        f"/api/v1/sales/{sale_id}/confirm",
        {"paid_amount": total, "method": "cash"},
    )
    return sale_id


def _receipt(client: TestClient, token: str, sale_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/sales/{sale_id}/receipt", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_a_line_carries_its_description_and_unit(api_client: TestClient, alpha_token: str) -> None:
    described = _stocked(api_client, alpha_token, unit="kg", description="Riz parfumé de la vallée")
    plain = _stocked(api_client, alpha_token)
    sale_id = _confirmed_sale(
        api_client,
        alpha_token,
        [{"product_id": described, "qty": "2.5"}, {"product_id": plain, "qty": "1"}],
    )
    lines = {
        line["product_id"]: line for line in _receipt(api_client, alpha_token, sale_id)["lines"]
    }
    assert lines[described]["description"] == "Riz parfumé de la vallée"
    assert lines[described]["unit"] == "kg"
    assert lines[plain]["description"] is None
    assert lines[plain]["unit"] == "piece"


def test_a_changed_price_is_never_told_to_the_customer(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le reçu montre le prix appliqué ; ni le prix de la fiche, ni la raison (ADR 0107)."""
    product_id = _stocked(api_client, alpha_token)
    sale_id = _confirmed_sale(
        api_client,
        alpha_token,
        [{"product_id": product_id, "qty": "1"}],
        price={"unit_price": "1200.00", "price_reason": "Fidèle"},
    )
    receipt = _receipt(api_client, alpha_token, sale_id)
    line = receipt["lines"][0]
    assert line["unit_price"] == "1200.00"
    assert "list_price" not in line and "price_reason" not in line
    assert "1500" not in str(receipt["lines"]) and "Fidèle" not in str(receipt)


def test_linked_returns_are_listed(api_client: TestClient, alpha_token: str) -> None:
    product_id = _stocked(api_client, alpha_token)
    sale_id = _confirmed_sale(api_client, alpha_token, [{"product_id": product_id, "qty": "3"}])
    assert _receipt(api_client, alpha_token, sale_id)["returns"] == []

    item_id = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token)).json()[
        "items"
    ][0]["id"]
    created = _post(
        api_client,
        alpha_token,
        f"/api/v1/sales/{sale_id}/returns",
        {"lines": [{"sale_item_id": item_id, "qty": "1"}], "reason": "Abîmé"},
    )
    returns = _receipt(api_client, alpha_token, sale_id)["returns"]
    assert [row["return_no"] for row in returns] == [created["return_no"]]
    assert returns[0]["total_refund"] == "1500.00"
    assert returns[0]["returned_at"]


def test_the_receipt_says_whether_a_logo_exists(api_client: TestClient, alpha_token: str) -> None:
    product_id = _stocked(api_client, alpha_token)
    sale_id = _confirmed_sale(api_client, alpha_token, [{"product_id": product_id, "qty": "1"}])
    headers = auth_headers(alpha_token)
    api_client.delete("/api/v1/companies/me/logo", headers=headers)
    assert _receipt(api_client, alpha_token, sale_id)["company"]["logo_updated_at"] is None

    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), (0, 0, 0)).save(buffer, format="PNG")
    put = api_client.put(
        "/api/v1/companies/me/logo",
        headers=headers,
        files={"file": ("logo.png", buffer.getvalue(), "image/png")},
    )
    assert put.status_code == 200, put.text
    try:
        stamped = _receipt(api_client, alpha_token, sale_id)["company"]["logo_updated_at"]
        assert stamped == put.json()["updated_at"]
    finally:
        api_client.delete("/api/v1/companies/me/logo", headers=headers)
