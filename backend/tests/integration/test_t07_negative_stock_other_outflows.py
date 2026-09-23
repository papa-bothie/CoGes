"""T7 — stock négatif sur les autres sorties : même refus, sans dérogation.

Le § 2.3 est explicite : la règle « s'applique indistinctement à la vente, à
l'ajustement négatif, à la perte, au retour fournisseur et à toute sortie future ».
Ce test le vérifie type par type, sur la base.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.errors import sqlstate
from app.core.tenancy import tenant_transaction
from tests.integration.stock_harness import insert_movement, make_product, read_stock
from tests.integration.test_t06_negative_stock_on_sale import INSUFFICIENT_STOCK
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("movement_type", ["adjustment", "loss", "supplier_return_out"])
def test_t07_negative_stock_on_other_outflows(
    session_factory: sessionmaker[Any], tenant_a: Tenant, movement_type: str
) -> None:
    """Sortie de 10 sur un stock de 5 : exception dans les trois cas."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "5", unit_cost="10")

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        insert_movement(session, tenant_a, product_id, movement_type, "-10", note="test")

    assert sqlstate(excinfo.value) == INSUFFICIENT_STOCK

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        stock = read_stock(session, product_id)

    assert stock.qty_on_hand == Decimal("5.000")
