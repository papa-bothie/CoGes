"""Un article épuisé ne se vend pas, même par un autre chemin (prompt 34, bloc E, ADR 0109).

Avant ce lot, le panier acceptait tout : `add_item` et `update_item` ne lisaient pas le
stock, seule la confirmation (CG020) refusait. Un article épuisé entrait donc dans le
panier par la recherche, la douchette, le bouton + ou un brouillon retrouvé.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, write_headers
from tests.integration.test_sales_api import _add_line, _draft

pytestmark = pytest.mark.integration


def _product(client: TestClient, token: str, *, stock: str | None, **body: Any) -> str:
    payload = {"name": f"Riz {uuid4().hex[:8]}", "unit_price": "1000", "unit": "sac", **body}
    created = client.post("/api/v1/products", headers=auth_headers(token), json=payload)
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
                "unit_cost": "600",
            },
        )
        assert moved.status_code == 201, moved.text
    return product_id


def _refusal(response: Any) -> dict[str, Any]:
    assert response.status_code == 409, response.text
    error: dict[str, Any] = response.json()["error"]
    assert error["code"] == "insufficient_stock"
    return error


def test_an_out_of_stock_article_never_enters_the_cart(
    api_client: TestClient, alpha_token: str
) -> None:
    """Grille, recherche, douchette : tous passent par l'ajout d'une ligne."""
    never_stocked = _product(api_client, alpha_token, stock=None)
    sale_id = _draft(api_client, alpha_token)
    error = _refusal(_add_line(api_client, alpha_token, sale_id, never_stocked, qty="1"))
    assert error["message"] == "Cet article est épuisé : il n'en reste plus."
    assert error["details"]["available"] == "0"


def test_adding_more_than_the_stock_is_refused(api_client: TestClient, alpha_token: str) -> None:
    product_id = _product(api_client, alpha_token, stock="3")
    sale_id = _draft(api_client, alpha_token)
    error = _refusal(_add_line(api_client, alpha_token, sale_id, product_id, qty="5"))
    assert error["message"] == "Il n'en reste que 3 sacs."
    assert error["details"]["product_id"] == product_id


def test_the_plus_button_stops_at_the_stock(api_client: TestClient, alpha_token: str) -> None:
    """Bouton + ou quantité tapée : `update_item` refuse au-delà du stock."""
    product_id = _product(api_client, alpha_token, stock="3")
    sale_id = _draft(api_client, alpha_token)
    item_id = _add_line(api_client, alpha_token, sale_id, product_id, qty="3").json()["id"]
    url = f"/api/v1/sales/{sale_id}/items/{item_id}"
    _refusal(api_client.patch(url, headers=auth_headers(alpha_token), json={"qty": "4"}))
    lowered = api_client.patch(url, headers=auth_headers(alpha_token), json={"qty": "2"})
    assert lowered.status_code == 200, "baisser reste permis"


def test_two_lines_of_the_same_article_count_together(
    api_client: TestClient, alpha_token: str
) -> None:
    product_id = _product(api_client, alpha_token, stock="3")
    sale_id = _draft(api_client, alpha_token)
    assert _add_line(api_client, alpha_token, sale_id, product_id, qty="2").status_code == 201
    error = _refusal(_add_line(api_client, alpha_token, sale_id, product_id, qty="2"))
    assert error["message"] == "Il n'en reste que 3 sacs."


def test_a_resumed_draft_is_refused_at_confirmation_with_the_same_words(
    api_client: TestClient, alpha_token: str
) -> None:
    """Brouillon retrouvé, ou deux caisses : la confirmation reste l'autorité finale."""
    product_id = _product(api_client, alpha_token, stock="3")
    first = _draft(api_client, alpha_token)
    second = _draft(api_client, alpha_token)
    _add_line(api_client, alpha_token, first, product_id, qty="2")
    _add_line(api_client, alpha_token, second, product_id, qty="2")

    sold = api_client.post(
        f"/api/v1/sales/{first}/confirm",
        headers=write_headers(alpha_token),
        json={"paid_amount": "2000", "method": "cash"},
    )
    assert sold.status_code == 200, sold.text
    error = _refusal(
        api_client.post(
            f"/api/v1/sales/{second}/confirm",
            headers=write_headers(alpha_token),
            json={"paid_amount": "2000", "method": "cash"},
        )
    )
    assert error["message"] == "Il n'en reste que 1 sac."
    assert (error["details"]["requested"], error["details"]["available"]) == ("2.000", "1.000")


def test_an_untracked_article_is_unchanged(api_client: TestClient, alpha_token: str) -> None:
    """Article non suivi en stock : aucune limite, comme avant (ADR 0109)."""
    product_id = _product(api_client, alpha_token, stock=None, is_stock_tracked=False)
    sale_id = _draft(api_client, alpha_token)
    assert _add_line(api_client, alpha_token, sale_id, product_id, qty="50").status_code == 201
