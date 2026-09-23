"""T10 — CMP à la sortie : le mouvement est estampillé, la moyenne ne bouge pas.

Une sortie ne change pas le coût moyen : elle en emporte une part. Son `unit_cost`
est figé au CMP applicable à cet instant, et c'est lui que le COGS relira — jamais
un coût d'aujourd'hui (§ 5.6).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import tenant_transaction
from tests.integration.stock_harness import insert_movement, make_product, read_stock
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration


def test_t10_outflow_is_stamped_at_the_current_average(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Après T9, sortie de 50 : unit_cost = 15, avg_cost = 15, valeur = 2250."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "100", unit_cost="10")
        insert_movement(session, tenant_a, product_id, "purchase_in", "100", unit_cost="20")

        # Coût volontairement absurde à la saisie : le trigger doit l'écraser.
        movement_id = insert_movement(
            session, tenant_a, product_id, "loss", "-50", unit_cost="999", note="casse"
        )
        stamped = session.execute(
            text("SELECT unit_cost FROM inventory_movements WHERE id = :id"),
            {"id": movement_id},
        ).scalar_one()
        stock = read_stock(session, product_id)

    assert stamped == Decimal("15.0000"), "la sortie porte le CMP, pas le coût saisi"
    assert stock.qty_on_hand == Decimal("150.000")
    assert stock.avg_cost == Decimal("15.0000")
    assert stock.stock_value == Decimal("2250.00")
