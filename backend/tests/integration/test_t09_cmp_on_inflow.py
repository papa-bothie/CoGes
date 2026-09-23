"""T9 — CMP à l'entrée : deux réceptions à des coûts différents.

100 unités à 10, puis 100 à 20. Le coût moyen pondéré vaut 15, et la valeur de
stock 3 000 — calculés par `cmp_next_avg` en base, jamais en Python (§ 5.6).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import tenant_transaction
from tests.integration.stock_harness import insert_movement, make_product, read_stock
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration


def test_t09_weighted_average_cost_on_inflow(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """avg_cost = 15.0000 et stock_value = 3000.00."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "100", unit_cost="10")
        insert_movement(session, tenant_a, product_id, "purchase_in", "100", unit_cost="20")
        stock = read_stock(session, product_id)

    assert stock.qty_on_hand == Decimal("200.000")
    assert stock.avg_cost == Decimal("15.0000")
    assert stock.stock_value == Decimal("3000.00")
