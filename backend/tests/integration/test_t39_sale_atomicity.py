"""T39 — atomicité de la confirmation : tout ou rien.

Deux angles, parce que la promesse a deux faces.

Le premier est littéral, celui du § 10 : un `ROLLBACK` injecté après les mouvements
ne doit rien laisser. Il attaque la base directement et ne prouve rien d'autre que
ce que PostgreSQL garantit — mais c'est précisément le socle sur lequel tout le
reste repose.

Le second est celui qui compte en production : une confirmation réelle, par l'API,
qui échoue sur sa **dernière** ligne faute de stock. Les deux premières sorties ont
déjà été écrites quand le refus tombe. Rien ne doit en rester : ni vente confirmée,
ni mouvement, ni paiement, ni événement, ni ligne d'audit.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant
from tests.integration.sales_harness import add_line, make_sale, sale_out
from tests.integration.stock_harness import (
    count_movements,
    insert_movement,
    make_product,
    read_stock,
)
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration


def test_t39_a_rollback_after_the_movements_leaves_nothing(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """T39 — ROLLBACK injecté après les mouvements : ni vente, ni mouvement, stock intact."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "50", unit_cost="10")

    ctx = TenantContext(user_id=tenant_a.user_id, company_id=tenant_a.company_id)
    session = session_factory()
    try:
        with session.begin():
            session.execute(
                text("SELECT set_config('app.company_id', :company_id, true)"),
                {"company_id": str(tenant_a.company_id)},
            )
            sale_id = make_sale(session, tenant_a)
            item_id = add_line(session, tenant_a, sale_id, product_id, qty="6", unit_price="1500")
            sale_out(session, tenant_a, product_id, item_id, "6")
            session.execute(
                text(
                    "INSERT INTO business_events "
                    "(company_id, event_type, aggregate_type, aggregate_id, payload) "
                    "VALUES (:company_id, 'sale.confirmed', 'sale', :sale_id, '{}'::jsonb)"
                ),
                {"company_id": tenant_a.company_id, "sale_id": sale_id},
            )
            # Tout est en place et cohérent. C'est ici que la transaction meurt.
            session.rollback()
    finally:
        session.close()

    with tenant_transaction(ctx, session_factory=session_factory) as session:
        sales = session.execute(
            text("SELECT count(*) FROM sales WHERE id = :id"), {"id": sale_id}
        ).scalar_one()
        events = session.execute(
            text("SELECT count(*) FROM business_events WHERE aggregate_id = :id"), {"id": sale_id}
        ).scalar_one()
        movements = count_movements(session, product_id)
        stock = read_stock(session, product_id)

    assert sales == 0, "aucune vente ne doit subsister"
    assert events == 0, "aucun événement ne doit subsister"
    assert movements == 1, "seul le mouvement initial doit rester"
    assert stock.qty_on_hand == Decimal("50.000"), "le stock doit être intact"


def test_t39_a_confirmation_failing_on_its_last_line_rolls_everything_back(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """T39 — la confirmation échoue sur la 3ᵉ ligne : les 2 premières sorties disparaissent.

    C'est le cas réel : un caissier scanne trois articles, le dernier n'est plus en
    stock. Sans atomicité, les deux premiers seraient sortis du stock pour une
    vente qui n'a jamais eu lieu — et le gérant chercherait longtemps.
    """
    headers = auth_headers(alpha_token)
    marker = uuid4().hex[:8]

    products: list[str] = []
    for index, stock_qty in enumerate(("10", "10", "1")):
        created = api_client.post(
            "/api/v1/products",
            headers=headers,
            json={
                "sku": f"SKU-{marker}-{index}",
                "name": f"Article {marker} {index}",
                "unit_price": "1500.00",
            },
        )
        assert created.status_code == 201, created.text
        product_id = str(created.json()["id"])
        products.append(product_id)
        stocked = api_client.post(
            "/api/v1/inventory/movements",
            headers=headers,
            json={
                "product_id": product_id,
                "type": "initial",
                "qty_delta": stock_qty,
                "unit_cost": "1000",
            },
        )
        assert stocked.status_code == 201, stocked.text

    sale = api_client.post("/api/v1/sales", headers=headers, json={})
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])

    for product_id in products:
        line = api_client.post(
            f"/api/v1/sales/{sale_id}/items",
            headers=headers,
            json={"product_id": product_id, "qty": "4"},
        )
        assert line.status_code == 201, line.text

    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=headers,
        json={"paid_amount": "18000.00", "method": "cash"},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "insufficient_stock"

    # La vente est restée un brouillon, et aucune trace n'a survécu.
    after = api_client.get(f"/api/v1/sales/{sale_id}", headers=headers)
    assert after.status_code == 200
    assert after.json()["status"] == "draft"
    assert after.json()["payments"] == []
    assert after.json()["debt"] is None

    stock = api_client.get(
        "/api/v1/inventory/stock",
        params=[("product_id", product_id) for product_id in products],
        headers=headers,
    )
    quantities = {row["product_id"]: Decimal(row["qty_on_hand"]) for row in stock.json()["items"]}
    assert [quantities[product_id] for product_id in products] == [
        Decimal("10.000"),
        Decimal("10.000"),
        Decimal("1.000"),
    ], "aucune sortie ne doit avoir survécu au refus"

    movements = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM inventory_movements WHERE type = 'sale_out' AND ref_id IN "
        "(SELECT id FROM sale_items WHERE sale_id = :sale_id)",
        {"sale_id": sale_id},
    )
    events = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM business_events WHERE aggregate_id = :sale_id",
        {"sale_id": sale_id},
    )
    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs WHERE entity_table = 'sales' AND entity_id = :sale_id",
        {"sale_id": sale_id},
    )

    assert movements == 0, "aucun mouvement de sortie ne doit subsister"
    assert events == 0, "aucun événement ne doit avoir été écrit"
    assert audited == 0, "aucune ligne d'audit ne doit avoir été écrite"
