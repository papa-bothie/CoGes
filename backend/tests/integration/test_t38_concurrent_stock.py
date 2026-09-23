"""T38 — deux caisses vendent la dernière unité : une seule y arrive.

C'est le test qui justifie le `SELECT … FOR UPDATE` de `inv_apply_movement`. Sans
ce verrou, les deux transactions liraient `qty_on_hand = 1`, concluraient toutes
les deux que la sortie est possible, et la projection finirait à −1 — ou pire, à 0
avec deux ventes enregistrées et un CMP faux.

Le test ne **court** pas après la fenêtre de concurrence, il la **provoque** : il
prend lui-même le verrou sur la ligne de stock, lance les deux sorties qui viennent
s'y heurter, puis relâche. Aucun `sleep` de complaisance, aucun résultat dépendant
de l'ordonnancement du système.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.database import create_app_engine
from app.core.errors import sqlstate
from app.core.tenancy import tenant_transaction
from tests.integration.stock_harness import (
    count_movements,
    insert_movement,
    make_product,
    read_stock,
)
from tests.integration.test_t06_negative_stock_on_sale import INSUFFICIENT_STOCK
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration


@pytest.fixture
def concurrent_session_factory(
    migrated_database: str, database_urls: tuple[str, str]
) -> Iterator[sessionmaker[Any]]:
    """Fabrique de sessions sur un pool de **trois** connexions.

    Le pool de la suite n'en contient qu'une — c'est ce qu'exige T4 pour prouver
    qu'aucun contexte ne survit au retour au pool. Il en faut trois ici : une pour
    le verrou tenu par le test, deux pour les caisses concurrentes.
    """
    _, app_url = database_urls
    engine: Engine = create_app_engine(app_url, pool_size=3, max_overflow=0)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()


def test_t38_only_one_transaction_gets_the_last_unit(
    concurrent_session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Une transaction réussit, l'autre lève ; ni stock négatif ni CMP faux."""
    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "1", unit_cost="42")

    def sell_one(_: int) -> str:
        """Une caisse qui sort la dernière unité."""
        try:
            with tenant_transaction(
                tenant_a.ctx, session_factory=concurrent_session_factory
            ) as session:
                insert_movement(session, tenant_a, product_id, "sale_out", "-1")
        except DBAPIError as exc:
            assert sqlstate(exc) == INSUFFICIENT_STOCK, str(exc)
            return "refus"
        return "succès"

    with ThreadPoolExecutor(max_workers=2) as pool:
        with tenant_transaction(
            tenant_a.ctx, session_factory=concurrent_session_factory
        ) as session:
            # 1. Le test s'approprie la ligne de stock : les deux caisses vont
            #    s'arrêter exactement là où le trigger prend son verrou.
            session.execute(
                text("SELECT qty_on_hand FROM product_stock WHERE product_id = :p FOR UPDATE"),
                {"p": product_id},
            )
            # 2. Les deux sorties partent et se bloquent.
            futures = [pool.submit(sell_one, index) for index in range(2)]
        # 3. Le COMMIT relâche le verrou : les deux reprennent, l'une après l'autre.
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == ["refus", "succès"], (
        f"exactement une sortie doit passer, obtenu : {outcomes}"
    )
    _assert_stock_is_sound(concurrent_session_factory, tenant_a, product_id)


def _assert_stock_is_sound(
    session_factory: sessionmaker[Any], tenant: Tenant, product_id: UUID
) -> None:
    """Après la bataille : zéro en stock, CMP intact, un seul mouvement de sortie."""
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        stock = read_stock(session, product_id)
        movements = count_movements(session, product_id)

    assert stock.qty_on_hand == Decimal("0.000"), "jamais de stock négatif"
    assert stock.avg_cost == Decimal("42.0000"), "le CMP survit à la concurrence"
    assert stock.stock_value == Decimal("0.00")
    assert movements == 2, "l'entrée et une seule sortie : la refusée n'a rien laissé"
