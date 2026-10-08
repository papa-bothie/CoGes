"""Raisons de correction du stock en liste fermée (ADR 0067).

« Corriger le stock » ne demande plus de motif écrit : une raison choisie dans une liste,
dont se déduit le type du mouvement (perte ou ajustement). La base refuse une raison qui ne
va pas avec le type ou le sens, même pour qui n'entre pas par l'API.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import DemoCompany, auth_headers

pytestmark = pytest.mark.integration

MOVEMENTS = "/api/v1/inventory/movements"


def _product_with_stock(client: TestClient, token: str) -> str:
    marker = uuid4().hex[:8]
    product = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"sku": f"RS-{marker}", "name": f"Article {marker}", "unit_price": "1000"},
    )
    assert product.status_code == 201, product.text
    product_id = str(product.json()["id"])
    opening = _record(client, token, product_id, type="initial", qty_delta="10", unit_cost="600")
    assert opening.status_code == 201, opening.text
    return product_id


def _record(client: TestClient, token: str, product_id: str, **fields: Any) -> Any:
    payload: dict[str, Any] = {"product_id": product_id, **fields}
    return client.post(MOVEMENTS, headers=auth_headers(token), json=payload)


@pytest.mark.parametrize(
    ("reason", "qty", "movement_type"),
    [
        ("damaged", "-1", "loss"),
        ("expired", "-1", "loss"),
        ("lost_or_stolen", "-2", "loss"),
        ("home_use", "-1", "loss"),
        ("count_error", "-1", "adjustment"),
        ("count_error", "2", "adjustment"),
        ("found", "1", "adjustment"),
        ("supplier_gift", "3", "adjustment"),
    ],
)
def test_the_type_follows_the_reason(
    api_client: TestClient, alpha_token: str, reason: str, qty: str, movement_type: str
) -> None:
    product_id = _product_with_stock(api_client, alpha_token)
    response = _record(api_client, alpha_token, product_id, reason_code=reason, qty_delta=qty)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["type"] == movement_type
    assert body["reason_code"] == reason
    assert body["note"] is None


def test_a_gain_is_valued_at_the_current_average(api_client: TestClient, alpha_token: str) -> None:
    product_id = _product_with_stock(api_client, alpha_token)
    found = _record(api_client, alpha_token, product_id, reason_code="found", qty_delta="1")
    assert found.status_code == 201, found.text
    assert found.json()["unit_cost"] == "600.0000"


@pytest.mark.parametrize("movement_type", ["adjustment", "loss"])
def test_a_correction_without_reason_is_refused(
    api_client: TestClient, alpha_token: str, movement_type: str
) -> None:
    """Le motif écrit ne suffit plus : la raison est obligatoire."""
    product_id = _product_with_stock(api_client, alpha_token)
    response = _record(
        api_client, alpha_token, product_id, type=movement_type, qty_delta="-1", note="cassé"
    )
    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert any("raison" in field["message"] for field in fields), fields


@pytest.mark.parametrize(
    ("fields", "why"),
    [
        ({"type": "loss", "reason_code": "count_error", "qty_delta": "-1"}, "type contraire"),
        ({"type": "adjustment", "reason_code": "damaged", "qty_delta": "-1"}, "type contraire"),
        ({"reason_code": "found", "qty_delta": "-1"}, "un article retrouvé s'ajoute"),
        ({"reason_code": "damaged", "qty_delta": "1"}, "une perte retire"),
        ({"type": "purchase_in", "reason_code": "found", "qty_delta": "1"}, "hors correction"),
    ],
)
def test_a_reason_that_does_not_fit_is_refused(
    api_client: TestClient, alpha_token: str, fields: dict[str, str], why: str
) -> None:
    product_id = _product_with_stock(api_client, alpha_token)
    response = _record(api_client, alpha_token, product_id, unit_cost=None, **fields)
    assert response.status_code == 422, why


def test_a_reasoned_correction_can_be_reversed(api_client: TestClient, alpha_token: str) -> None:
    product_id = _product_with_stock(api_client, alpha_token)
    loss = _record(api_client, alpha_token, product_id, reason_code="damaged", qty_delta="-1")
    reversal = api_client.post(
        f"{MOVEMENTS}/{loss.json()['id']}/reverse", headers=auth_headers(alpha_token)
    )
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["reason_code"] is None


def test_the_journal_returns_the_reason(api_client: TestClient, alpha_token: str) -> None:
    product_id = _product_with_stock(api_client, alpha_token)
    _record(api_client, alpha_token, product_id, reason_code="expired", qty_delta="-1")
    journal = api_client.get(
        f"{MOVEMENTS}?product_id={product_id}&type=loss", headers=auth_headers(alpha_token)
    )
    assert journal.json()["items"][0]["reason_code"] == "expired"


@pytest.mark.parametrize(
    ("movement_type", "qty", "reason"),
    [("loss", "-1", "found"), ("adjustment", "-1", "supplier_gift"), ("purchase_in", "1", "found")],
)
def test_the_database_refuses_a_reason_that_does_not_fit(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    movement_type: str,
    qty: str,
    reason: str,
) -> None:
    """`inv_reason_coherent`, attaqué en SQL : l'API n'est pas la seule barrière."""
    product_id = _product_with_stock(api_client, alpha_token)
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)
    with (
        pytest.raises(IntegrityError, match="inv_reason_coherent"),
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO inventory_movements"
                " (company_id, product_id, type, qty_delta, unit_cost, reason_code)"
                " VALUES (:co, :product, CAST(:type AS movement_type), :qty, 600,"
                " CAST(:reason AS stock_reason))"
            ),
            {
                "co": company_alpha.company_id,
                "product": product_id,
                "type": movement_type,
                "qty": qty,
                "reason": reason,
            },
        )
