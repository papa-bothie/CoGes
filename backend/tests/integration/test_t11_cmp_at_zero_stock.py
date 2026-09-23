"""T11 — stock ramené à zéro : pas de division par zéro, CMP conservé.

C'est le garde-fou `WHEN p_qty + p_delta = 0 THEN p_avg` de `cmp_next_avg`. Sans
lui, vider un article produirait une division 0/0 et rendrait la projection
inexploitable pour le prochain réapprovisionnement.
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


def test_t11_emptying_the_stock_keeps_the_average(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """qty_on_hand = 0, avg_cost conservé, stock_value = 0, aucune erreur."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "100", unit_cost="10")
        insert_movement(session, tenant_a, product_id, "purchase_in", "100", unit_cost="20")
        insert_movement(session, tenant_a, product_id, "loss", "-200", note="sinistre")
        stock = read_stock(session, product_id)

    assert stock.qty_on_hand == Decimal("0.000")
    assert stock.avg_cost == Decimal("15.0000"), "le dernier CMP connu est conservé"
    assert stock.stock_value == Decimal("0.00")


def test_t11_restocking_after_zero_starts_from_the_new_cost(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Réapprovisionner un article vidé donne exactement le coût de la réception."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "10", unit_cost="10")
        insert_movement(session, tenant_a, product_id, "loss", "-10", note="sinistre")
        insert_movement(session, tenant_a, product_id, "purchase_in", "4", unit_cost="25")
        stock = read_stock(session, product_id)

    assert stock.qty_on_hand == Decimal("4.000")
    assert stock.avg_cost == Decimal("25.0000")
    assert stock.stock_value == Decimal("100.00")
