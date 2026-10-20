"""Le sous-total d'une vente arrondit ligne par ligne (P2.13, ADR 0088).

`net_amount` et `line_total` arrondissent **chaque ligne** ; `sale_recompute_totals`
arrondissait la **somme** (`SUM(qty × unit_price)`). Avec des quantités décimales — du
riz au kilo —, le total de la vente ne valait plus la somme de ses lignes : 1,5 kg à
333,33 donne 499,995, soit 500,00 par ligne et 1 000,00 pour deux lignes, mais 999,99
pour la vente. Le ticket ne se recompte pas.

SQL direct sous `coges_app` : c'est le trigger qui tient la règle.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import tenant_transaction
from tests.integration.sales_harness import add_line, make_sale
from tests.integration.stock_harness import make_product
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration


def test_the_sale_total_is_the_sum_of_its_lines(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        sale_id = make_sale(session, tenant_a)
        for _ in range(2):
            add_line(
                session,
                tenant_a,
                sale_id,
                make_product(session, tenant_a),
                qty="1.5",
                unit_price="333.33",
            )
        sale = session.execute(
            text("SELECT subtotal, total FROM sales WHERE id = :id"), {"id": sale_id}
        ).one()
        lines = session.execute(
            text("SELECT sum(line_total) FROM sale_items WHERE sale_id = :id"), {"id": sale_id}
        ).scalar_one()

    assert Decimal(lines) == Decimal("1000.00")
    assert Decimal(sale.subtotal) == Decimal("1000.00"), "sous-total arrondi sur la somme"
    assert Decimal(sale.total) == Decimal(lines), "le total ne vaut pas la somme des lignes"
