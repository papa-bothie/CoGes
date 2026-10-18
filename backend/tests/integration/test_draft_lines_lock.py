"""Une ligne ajoutée pendant la confirmation (prompt 21, P1.4 ; ADR 0087).

`confirm_sale` verrouille la vente (`FOR UPDATE`) ; `add_item`, `update_item` et
`remove_item` la lisaient sans verrou. Une ligne écrite pendant la confirmation passait
`sale_items_no_change` (le brouillon était encore `draft` pour elle), puis son
recalcul des totaux attendait le COMMIT de la confirmation et changeait le total
**après** le calcul de la dette — sans sortie de stock ni coût.

Comme T20 et T38, le test **provoque** la fenêtre au lieu de courir après : une
troisième connexion tient la vente, la confirmation s'y bloque la première, l'ajout de
ligne ensuite, et c'est le test qui relâche le verrou.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import text

from app.core.database import create_app_engine
from app.core.errors import BusinessRuleError
from app.core.tenancy import tenant_transaction
from app.modules.sales import service as sales_service
from app.modules.sales.schemas import SaleConfirm, SaleItemCreate, SaleItemUpdate
from tests.helpers.invariants import assert_consistent
from tests.integration.sales_harness import add_line, make_sale
from tests.integration.stock_harness import insert_movement, make_product
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

_LOCK_SALE = text("SELECT id FROM sales WHERE id = :id FOR UPDATE")
_PRICE = text(
    """
    INSERT INTO product_prices (company_id, product_id, unit_price, created_by)
    VALUES (:company_id, :product_id, 1000, :user_id)
    """
)
#: Lu depuis la connexion qui tient le verrou : `coges_app` voit l'état de ses propres
#: sessions. `pg_stat_clear_snapshot` : sans lui, la vue resterait figée sur la
#: première lecture de la transaction.
_LOCK_WAITERS = text(
    """
    SELECT count(*) FROM pg_stat_activity
     WHERE wait_event_type = 'Lock' AND datname = current_database()
    """
)


_CLEAR_SNAPSHOT = text("SELECT pg_stat_clear_snapshot()")


@pytest.fixture
def concurrent_session_factory(
    migrated_database: str, database_urls: tuple[str, str]
) -> Iterator[sessionmaker[Any]]:
    """Trois connexions : le verrou du test, la confirmation, l'écriture de ligne."""
    _, app_url = database_urls
    engine: Engine = create_app_engine(app_url, pool_size=3, max_overflow=0)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()


def _sellable(session: Session, tenant: Tenant) -> UUID:
    product_id = make_product(session, tenant)
    session.execute(
        _PRICE,
        {"company_id": tenant.company_id, "product_id": product_id, "user_id": tenant.user_id},
    )
    insert_movement(session, tenant, product_id, "initial", "100", unit_cost="10")
    return product_id


def _wait_for_waiters(holder: Session, expected: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        holder.execute(_CLEAR_SNAPSHOT)
        if holder.execute(_LOCK_WAITERS).scalar_one() >= expected:
            return
        time.sleep(0.05)
    raise AssertionError(f"{expected} transaction(s) bloquée(s) attendue(s)")


def _race(
    factory: sessionmaker[Any],
    tenant: Tenant,
    sale_id: UUID,
    edit: Callable[[Session], Any],
) -> tuple[Future[Any], Future[Any]]:
    """La confirmation se bloque la première sur la vente, l'écriture ensuite."""

    def confirm() -> None:
        with tenant_transaction(tenant.ctx, session_factory=factory) as session:
            sales_service.confirm_sale(session, tenant.ctx, sale_id, SaleConfirm())

    def write() -> None:
        with tenant_transaction(tenant.ctx, session_factory=factory) as session:
            edit(session)

    pool = ThreadPoolExecutor(max_workers=2)
    with tenant_transaction(tenant.ctx, session_factory=factory) as holder:
        holder.execute(_LOCK_SALE, {"id": sale_id})
        confirmed = pool.submit(confirm)
        _wait_for_waiters(holder, 1)
        written = pool.submit(write)
        # L'écriture attend aussi : au verrou de la vente avec le correctif, au
        # recalcul des totaux sans lui. Dans les deux cas, derrière la confirmation.
        _wait_for_waiters(holder, 2)
    pool.shutdown(wait=True)
    return confirmed, written


def _draft(factory: sessionmaker[Any], tenant: Tenant) -> tuple[UUID, UUID, UUID]:
    with tenant_transaction(tenant.ctx, session_factory=factory) as session:
        first = _sellable(session, tenant)
        second = _sellable(session, tenant)
        sale_id = make_sale(session, tenant, customer_id=tenant.customer_id)
        item_id = add_line(session, tenant, sale_id, first, qty="2")
    return sale_id, item_id, second


def _assert_refused_as_not_draft(written: Future[Any]) -> None:
    error = written.exception()
    assert isinstance(error, BusinessRuleError), (
        f"l'écriture d'une ligne a passé pendant la confirmation : {error!r}"
    )
    assert error.code == "sale_not_draft"


def test_a_line_added_during_confirmation_is_refused(
    concurrent_session_factory: sessionmaker[Any], owner_engine: Engine, tenant_a: Tenant
) -> None:
    sale_id, _, second = _draft(concurrent_session_factory, tenant_a)

    confirmed, written = _race(
        concurrent_session_factory,
        tenant_a,
        sale_id,
        lambda session: sales_service.add_item(
            session, tenant_a.ctx, sale_id, SaleItemCreate(product_id=second, qty=Decimal("3"))
        ),
    )

    assert confirmed.exception() is None
    _assert_refused_as_not_draft(written)
    assert_consistent(owner_engine, tenant_a.company_id)


def test_a_line_changed_during_confirmation_is_refused(
    concurrent_session_factory: sessionmaker[Any], owner_engine: Engine, tenant_a: Tenant
) -> None:
    sale_id, item_id, _ = _draft(concurrent_session_factory, tenant_a)

    confirmed, written = _race(
        concurrent_session_factory,
        tenant_a,
        sale_id,
        lambda session: sales_service.update_item(
            session, tenant_a.ctx, sale_id, item_id, SaleItemUpdate(qty=Decimal("5"))
        ),
    )

    assert confirmed.exception() is None
    _assert_refused_as_not_draft(written)
    assert_consistent(owner_engine, tenant_a.company_id)


def test_a_customer_changed_during_confirmation_is_refused(
    concurrent_session_factory: sessionmaker[Any], owner_engine: Engine, tenant_a: Tenant
) -> None:
    from app.modules.sales.schemas import SaleUpdate  # noqa: PLC0415

    sale_id, _, _ = _draft(concurrent_session_factory, tenant_a)

    confirmed, written = _race(
        concurrent_session_factory,
        tenant_a,
        sale_id,
        lambda session: sales_service.update_sale(
            session, tenant_a.ctx, sale_id, SaleUpdate(customer_id=None)
        ),
    )

    assert confirmed.exception() is None
    _assert_refused_as_not_draft(written)
    assert_consistent(owner_engine, tenant_a.company_id)
