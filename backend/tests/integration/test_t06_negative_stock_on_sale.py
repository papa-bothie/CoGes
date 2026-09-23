"""T6 — stock négatif à la vente : rejet atomique, projection intacte.

Le mouvement de sortie est inséré **directement en SQL**, comme le ferait la
confirmation d'une vente en phase 05. Le refus ne vient donc ni du schéma Pydantic,
ni du service : c'est PostgreSQL qui tranche (§ 2.3).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.errors import sqlstate
from app.core.tenancy import tenant_transaction
from tests.integration.stock_harness import (
    count_movements,
    insert_movement,
    make_product,
    read_stock,
)
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: SQLSTATE applicatif du stock négatif (migration 0004, ADR 0018).
INSUFFICIENT_STOCK = "CG020"


def test_t06_negative_stock_on_sale(session_factory: sessionmaker[Any], tenant_a: Tenant) -> None:
    """Stock 5, vente de 6 : exception, transaction annulée, stock resté à 5."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "5", unit_cost="10")

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        insert_movement(session, tenant_a, product_id, "sale_out", "-6")

    assert sqlstate(excinfo.value) == INSUFFICIENT_STOCK
    assert "disponible 5.000" in str(excinfo.value)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        stock = read_stock(session, product_id)
        movements = count_movements(session, product_id)

    assert stock.qty_on_hand == Decimal("5.000")
    assert movements == 1, "le mouvement refusé ne doit laisser aucune trace"
