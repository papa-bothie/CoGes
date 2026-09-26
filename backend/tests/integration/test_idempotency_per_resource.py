"""Une clé d'idempotence vaut pour **une** ressource (ADR 0039).

`POST /sales/{id}/confirm` et `POST /sale-returns/{id}/refunds` enregistrent
l'identifiant de la ressource dans l'endpoint de la clé, comme
`POST /payments/{id}/cancel`. Sans cela, deux ventes au même corps (même montant,
même moyen) partagent l'empreinte : la même clé présentée pour la seconde
**rejouerait** la réponse de la première, et la seconde ne serait jamais confirmée.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.idempotency import REPLAY_HEADER
from tests.conftest import auth_headers, write_headers

pytestmark = pytest.mark.integration

CONFIRM_BODY = {"paid_amount": "2360.00", "method": "cash"}
REFUND_BODY = {"amount": "1180.00", "method": "cash"}


def _product(client: TestClient, token: str) -> str:
    """Un produit à 1 000 HT, taxé à 18 %, garni de 100 unités au coût de 600."""
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={
            "sku": f"SKU-{marker}",
            "name": f"Article {marker}",
            "unit_price": "1000.00",
            "default_tax_rate": "0.1800",
        },
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


def _draft(client: TestClient, token: str, product_id: str) -> str:
    """Brouillon de deux unités : 2 360 TTC, le montant de `CONFIRM_BODY`."""
    sale = client.post("/api/v1/sales", headers=auth_headers(token), json={})
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])
    item = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(token),
        json={"product_id": product_id, "qty": "2"},
    )
    assert item.status_code == 201, item.text
    return sale_id


def _confirm(client: TestClient, token: str, sale_id: str, key: str | None = None) -> Any:
    return client.post(
        f"/api/v1/sales/{sale_id}/confirm", headers=write_headers(token, key), json=CONFIRM_BODY
    )


def _sale(client: TestClient, token: str, sale_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _return_of_one_unit(client: TestClient, token: str, sale_id: str) -> str:
    sale = _sale(client, token, sale_id)
    created = client.post(
        f"/api/v1/sales/{sale_id}/returns",
        headers=auth_headers(token),
        json={"lines": [{"sale_item_id": sale["items"][0]["id"], "qty": "1"}]},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _refund(client: TestClient, token: str, return_id: str, key: str) -> Any:
    return client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=write_headers(token, key),
        json=REFUND_BODY,
    )


def test_the_same_key_on_the_same_sale_is_still_a_replay(
    api_client: TestClient, alpha_token: str
) -> None:
    sale_id = _draft(api_client, alpha_token, _product(api_client, alpha_token))
    key = uuid4().hex

    first = _confirm(api_client, alpha_token, sale_id, key)
    replay = _confirm(api_client, alpha_token, sale_id, key)
    assert first.status_code == replay.status_code == 200, replay.text
    assert replay.headers.get(REPLAY_HEADER) == "true"
    assert first.json() == replay.json()


def test_the_same_key_on_another_sale_is_refused_not_replayed(
    api_client: TestClient, alpha_token: str
) -> None:
    product_id = _product(api_client, alpha_token)
    first_id = _draft(api_client, alpha_token, product_id)
    second_id = _draft(api_client, alpha_token, product_id)
    key = uuid4().hex

    assert _confirm(api_client, alpha_token, first_id, key).status_code == 200
    reused = _confirm(api_client, alpha_token, second_id, key)

    assert reused.status_code == 422, reused.text
    assert reused.headers.get(REPLAY_HEADER) is None
    assert reused.json()["error"]["code"] == "idempotency_key_reused"
    second = _sale(api_client, alpha_token, second_id)
    assert second["status"] == "draft"
    assert second["paid_total"] == "0.00"


def test_the_same_key_on_another_return_is_refused_not_replayed(
    api_client: TestClient, alpha_token: str
) -> None:
    product_id = _product(api_client, alpha_token)
    returns = []
    for _ in range(2):
        sale_id = _draft(api_client, alpha_token, product_id)
        assert _confirm(api_client, alpha_token, sale_id).status_code == 200
        returns.append(_return_of_one_unit(api_client, alpha_token, sale_id))
    key = uuid4().hex

    assert _refund(api_client, alpha_token, returns[0], key).status_code == 200
    reused = _refund(api_client, alpha_token, returns[1], key)

    assert reused.status_code == 422, reused.text
    assert reused.json()["error"]["code"] == "idempotency_key_reused"
    untouched = api_client.get(
        f"/api/v1/sale-returns/{returns[1]}", headers=auth_headers(alpha_token)
    ).json()
    assert (untouched["refunded_total"], untouched["refund_status"]) == ("0.00", "pending")
    assert untouched["payments"] == []
