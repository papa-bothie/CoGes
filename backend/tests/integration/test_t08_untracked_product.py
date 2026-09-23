"""T8 — article non suivi : aucun mouvement, aucune projection.

Un article `is_stock_tracked = false` n'a pas de stock du tout : le CMP n'aurait
aucun sens pour lui (§ 2.3). Le refus doit donc intervenir **avant** la création de
la ligne de projection — sinon la table se remplirait d'articles à zéro que rien ne
peut faire bouger.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.errors import sqlstate
from app.core.tenancy import tenant_transaction
from tests.integration.stock_harness import insert_movement, make_product, read_stock
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: SQLSTATE applicatif du produit non suivi (migration 0004, ADR 0018).
NOT_STOCK_TRACKED = "CG021"


def test_t08_untracked_product_refuses_every_movement(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Mouvement sur un article non suivi : exception, et aucune ligne de stock."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a, is_stock_tracked=False)

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        insert_movement(session, tenant_a, product_id, "initial", "10", unit_cost="100")

    assert sqlstate(excinfo.value) == NOT_STOCK_TRACKED

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        assert read_stock(session, product_id) is None, (
            "aucune ligne de product_stock ne doit exister pour un article non suivi"
        )
