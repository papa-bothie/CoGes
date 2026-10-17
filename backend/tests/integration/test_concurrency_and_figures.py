"""Concurrence par l'API, et chiffres qui se recoupent (lot C, C5 ; ADR 0086).

Au niveau des mouvements et des services, la concurrence est prouvée par T38 (dernière
unité), T26 (règlements sur une dette), T18-T20 (retours) et
`test_payments_idempotency.py::test_two_concurrent_requests_with_the_same_key_write_once`
(double clic, même clé). Ici, les mêmes courses **par HTTP**, comme deux caisses :

* deux confirmations simultanées se disputent le dernier article : une seule réussit,
  l'autre reçoit « Stock insuffisant », le stock n'est jamais négatif ;
* deux règlements différents en parallèle sur la même dette : leur somme ne dépasse
  jamais la dette.

Après chaque scénario, `tests/helpers/invariants.py` recoupe stock, ventes, dettes et
lettrages, et le chiffre d'affaires du jour du tableau de bord est recalculé à part.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from app.core import cache
from app.main import app
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    write_headers,
)
from tests.helpers.invariants import assert_consistent

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def shop(app_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"course-{uuid4().hex[:6]}")


@pytest.fixture
def token(shop: DemoCompany) -> Iterator[str]:
    with TestClient(app, base_url=TEST_BASE_URL) as client:
        yield login_token(client, shop)


def _post(client: TestClient, token: str, path: str, body: Any) -> dict[str, Any]:
    response = client.post(path, headers=write_headers(token), json=body)
    assert response.status_code in (200, 201), f"{path} : {response.text}"
    return dict(response.json())


def _race(calls: list[Callable[[TestClient], Any]]) -> list[Any]:
    """Chaque appel sur son propre client, lancés ensemble."""
    clients = [TestClient(app, base_url=TEST_BASE_URL) for _ in calls]
    for client in clients:
        client.__enter__()
    try:
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return list(pool.map(lambda pair: pair[0](pair[1]), zip(calls, clients, strict=True)))
    finally:
        for client in clients:
            client.__exit__(None, None, None)


def _dashboard_matches_sales(token: str, shop: DemoCompany, owner_engine: Engine) -> None:
    """CA du jour du tableau de bord = ventes confirmées du jour, recalculées en SQL."""
    zone = ZoneInfo("Africa/Dakar")
    today = datetime.now(zone).date()
    start = datetime.combine(today, time.min, tzinfo=zone)
    end = datetime.combine(today, time.max, tzinfo=zone)
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(shop.company_id)}
        )
        gross = connection.execute(
            text(
                """
                SELECT coalesce(sum(round(i.qty * i.unit_price, 2) - i.discount), 0)
                FROM sale_items i JOIN sales s ON s.id = i.sale_id
                WHERE s.status = 'confirmed' AND s.sold_at BETWEEN :start AND :end
                """
            ),
            {"start": start, "end": end},
        ).scalar_one()
        refunded = connection.execute(
            text(
                """
                SELECT coalesce(sum(r.refund_amount - r.tax_refund), 0)
                FROM sale_return_items r
                JOIN sale_items i ON i.id = r.sale_item_id
                JOIN sales s ON s.id = i.sale_id
                WHERE s.status = 'confirmed' AND s.sold_at BETWEEN :start AND :end
                """
            ),
            {"start": start, "end": end},
        ).scalar_one()
    cache.invalidate(shop.company_id, cache.DASHBOARD_KEY)
    with TestClient(app, base_url=TEST_BASE_URL) as client:
        dashboard = client.get("/api/v1/dashboard", headers=auth_headers(token)).json()
    assert Decimal(dashboard["revenue_today"]) == Decimal(gross) - Decimal(refunded)


def test_two_tills_selling_the_last_unit(
    shop: DemoCompany, token: str, owner_engine: Engine
) -> None:
    with TestClient(app, base_url=TEST_BASE_URL) as client:
        product = _post(
            client,
            token,
            "/api/v1/products",
            {"name": f"Dernier {uuid4().hex[:6]}", "unit_price": "1000"},
        )
        _post(
            client,
            token,
            "/api/v1/inventory/movements",
            {"product_id": product["id"], "type": "initial", "qty_delta": "1", "unit_cost": "600"},
        )
        drafts = []
        for _ in range(2):
            sale = _post(client, token, "/api/v1/sales", {})
            _post(
                client,
                token,
                f"/api/v1/sales/{sale['id']}/items",
                {"product_id": product["id"], "qty": "1"},
            )
            drafts.append(sale["id"])

    def confirm(sale_id: str) -> Callable[[TestClient], Any]:
        return lambda client: client.post(
            f"/api/v1/sales/{sale_id}/confirm",
            headers=write_headers(token),
            json={"paid_amount": "1000", "method": "cash"},
        )

    responses = _race([confirm(sale_id) for sale_id in drafts])
    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 409], [r.text for r in responses]
    refused = next(r for r in responses if r.status_code == 409)
    assert refused.json()["error"]["code"] == "insufficient_stock"

    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(shop.company_id)}
        )
        qty, avg_cost = connection.execute(
            text("SELECT qty_on_hand, avg_cost FROM product_stock WHERE product_id = :p"),
            {"p": product["id"]},
        ).one()
    assert qty == Decimal("0.000")
    assert avg_cost == Decimal("600.0000"), "le CMP ne bouge pas sur une sortie"
    assert_consistent(owner_engine, shop.company_id)
    _dashboard_matches_sales(token, shop, owner_engine)


def test_two_different_settlements_never_exceed_the_debt(
    shop: DemoCompany, token: str, owner_engine: Engine
) -> None:
    with TestClient(app, base_url=TEST_BASE_URL) as client:
        product = _post(
            client,
            token,
            "/api/v1/products",
            {"name": f"Crédit {uuid4().hex[:6]}", "unit_price": "1000"},
        )
        _post(
            client,
            token,
            "/api/v1/inventory/movements",
            {"product_id": product["id"], "type": "initial", "qty_delta": "5", "unit_cost": "600"},
        )
        customer = _post(client, token, "/api/v1/customers", {"name": f"Client {uuid4().hex[:6]}"})
        sale = _post(client, token, "/api/v1/sales", {"customer_id": customer["id"]})
        _post(
            client,
            token,
            f"/api/v1/sales/{sale['id']}/items",
            {"product_id": product["id"], "qty": "1"},
        )
        _post(
            client,
            token,
            f"/api/v1/sales/{sale['id']}/confirm",
            {"paid_amount": "0", "method": "cash"},
        )
        debt = client.get(
            f"/api/v1/debts?customer_id={customer['id']}", headers=auth_headers(token)
        ).json()["items"][0]

    def settle(client: TestClient) -> Any:
        return client.post(
            "/api/v1/payments",
            headers=write_headers(token),
            json={
                "direction": "inflow",
                "method": "cash",
                "amount": "700",
                "allocations": [{"debt_id": debt["id"], "amount": "700"}],
            },
        )

    responses = _race([settle, settle])
    succeeded = [r for r in responses if r.status_code == 201]
    assert len(succeeded) == 1, [r.text for r in responses]
    assert next(r for r in responses if r.status_code != 201).status_code in (409, 422)

    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(shop.company_id)}
        )
        principal, paid = connection.execute(
            text("SELECT principal, amount_paid FROM debts WHERE id = :d"), {"d": debt["id"]}
        ).one()
    assert paid == Decimal("700.00") and paid <= principal
    assert_consistent(owner_engine, shop.company_id)
    _dashboard_matches_sales(token, shop, owner_engine)
