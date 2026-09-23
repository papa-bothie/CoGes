"""T12 — reconstruction : trigger et recalcul donnent le même résultat.

`product_stock` est une projection, donc entièrement recalculable (§ 5.7). La
quantité est une somme, mais le CMP dépend de l'**ordre** des mouvements : la
reconstruction rejoue le journal par `(occurred_at, id)` croissant et applique la
même fonction `cmp_next_avg` que le trigger. C'est ce partage délibéré qui rend
toute divergence impossible — et c'est exactement ce que mesure ce test.

Les dates sont strictement croissantes, ce qui est le cas normal : l'ordre canonique
du recalcul coïncide alors avec l'ordre d'insertion. Un mouvement antidaté les
désaccorderait, ce que la fenêtre de 48 h borne par ailleurs (ADR 0015, couverte par
`test_inventory_backdating.py`).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import tenant_transaction
from tests.integration.stock_harness import insert_movement, make_product, read_stock
from tests.tenancy.harness import Tenant, create_tenant

pytestmark = pytest.mark.integration

MOVEMENT_COUNT = 200
PRODUCT_COUNT = 4


@pytest.fixture(scope="module")
def rebuild_tenant(session_factory: sessionmaker[Any], owner_engine: Engine) -> Tenant:
    """Une entreprise rien que pour ce test.

    `rebuild_product_stock` porte sur **toute** l'entreprise, pas sur un produit :
    les articles antidatés d'un autre test y produiraient un écart parfaitement
    légitime, qui n'apprendrait rien sur la formule du CMP.
    """
    return create_tenant(session_factory, owner_engine, "entreprise-rebuild")


def test_t12_rebuild_matches_the_trigger(
    session_factory: sessionmaker[Any], rebuild_tenant: Tenant
) -> None:
    """200 mouvements aléatoires, puis reconstruction : écart nul sur qty et sur avg."""
    generator = random.Random(20260923)  # noqa: S311 - aléa de test, pas de cryptographie
    start = datetime.now(UTC) - timedelta(hours=1)

    with tenant_transaction(rebuild_tenant.ctx, session_factory=session_factory) as session:
        products = [make_product(session, rebuild_tenant) for _ in range(PRODUCT_COUNT)]
        # Le stock doit rester positif : chaque article démarre haut, et les
        # sorties restent petites. Un stock négatif n'est pas ce qu'on teste ici.
        # Le stock initial est daté **avant** tout le reste : sans cela il passerait
        # en dernier dans l'ordre canonique, et le recalcul divergerait à juste
        # titre — c'est le mécanisme même de l'antidatage.
        for product_id in products:
            insert_movement(
                session,
                rebuild_tenant,
                product_id,
                "initial",
                "1000",
                unit_cost="10",
                occurred_at=start,
            )

        for step in range(1, MOVEMENT_COUNT + 1):
            product_id = generator.choice(products)
            occurred_at = start + timedelta(seconds=step)
            if generator.random() < 0.5:
                insert_movement(
                    session,
                    rebuild_tenant,
                    product_id,
                    "purchase_in",
                    str(generator.randint(1, 50)),
                    unit_cost=str(generator.randint(5, 40)),
                    occurred_at=occurred_at,
                )
            else:
                insert_movement(
                    session,
                    rebuild_tenant,
                    product_id,
                    "loss",
                    f"-{generator.randint(1, 20)}",
                    note="aléa",
                    occurred_at=occurred_at,
                )

        before = {product_id: read_stock(session, product_id) for product_id in products}

    # Une transaction dédiée : `_rebuilt` est une table temporaire ON COMMIT DROP.
    with tenant_transaction(rebuild_tenant.ctx, session_factory=session_factory) as session:
        gaps = session.execute(
            text("SELECT * FROM rebuild_product_stock(:company_id)"),
            {"company_id": rebuild_tenant.company_id},
        ).all()

    assert gaps == [], f"le recalcul diverge du trigger : {gaps}"

    with tenant_transaction(rebuild_tenant.ctx, session_factory=session_factory) as session:
        after = {product_id: read_stock(session, product_id) for product_id in products}

    for product_id in products:
        assert after[product_id].qty_on_hand == before[product_id].qty_on_hand
        assert after[product_id].avg_cost == before[product_id].avg_cost
        assert after[product_id].qty_on_hand > Decimal("0")
