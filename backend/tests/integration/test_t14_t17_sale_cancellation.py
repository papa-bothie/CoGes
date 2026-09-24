"""T14 à T17 — annulation d'une vente, idempotence et unicité, prouvées sur la base.

Ces tests n'appellent ni l'API ni le service : ils ouvrent une transaction en
`coges_app`, posent le contexte et attaquent PostgreSQL. Ce qui est mesuré ici, ce
sont les garanties **structurelles** du § 8.5 — `inv_reversal_uq`,
`inv_ref_idempotence` et `inv_check_reversal` — qui tiennent quel que soit
l'appelant, y compris celui qui contournerait l'API.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.errors import constraint_name, sqlstate
from app.core.tenancy import tenant_transaction
from tests.integration.sales_harness import (
    add_line,
    confirm,
    make_sale,
    movements_for_sale,
    reverse,
    sale_out,
)
from tests.integration.stock_harness import (
    count_movements,
    insert_movement,
    make_product,
    read_stock,
)
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

_UNIQUE_VIOLATION = "23505"


def _confirmed_sale(
    session_factory: sessionmaker[Any], tenant: Tenant, *, lines: int = 3
) -> tuple[Any, list[Any], list[Any]]:
    """Une vente confirmée de `lines` lignes, chacune sur son propre produit.

    Rend `(sale_id, product_ids, movement_ids)`. Chaque produit reçoit un stock
    initial de 100 au coût de 10, pour que le CMP soit connu et stable.
    """
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        product_ids = [make_product(session, tenant) for _ in range(lines)]
        for product_id in product_ids:
            insert_movement(session, tenant, product_id, "initial", "100", unit_cost="10")

        sale_id = make_sale(session, tenant, customer_id=tenant.customer_id)
        item_ids = [
            add_line(session, tenant, sale_id, product_id, qty="4", unit_price="1500")
            for product_id in product_ids
        ]
        movement_ids = [
            sale_out(session, tenant, product_id, item_id, "4")
            for product_id, item_id in zip(product_ids, item_ids, strict=True)
        ]
        confirm(session, tenant, sale_id)

    return sale_id, product_ids, movement_ids


def test_t14_cancellation_writes_one_reversal_per_line(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """T14 — un inverse par ligne, `reversal_of_movement_id` renseigné, stock rendu."""
    sale_id, product_ids, _ = _confirmed_sale(session_factory, tenant_a)

    # Après la vente, chaque produit est descendu de 100 à 96.
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        after_sale = [read_stock(session, product_id).qty_on_hand for product_id in product_ids]
    assert after_sale == [Decimal("96.000")] * 3

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        for movement in movements_for_sale(session, tenant_a, sale_id):
            reverse(session, tenant_a, movement)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        movements = movements_for_sale(session, tenant_a, sale_id)
        restored = [read_stock(session, product_id).qty_on_hand for product_id in product_ids]
        costs = [read_stock(session, product_id).avg_cost for product_id in product_ids]

    reversals = [row for row in movements if row.reversal_of_movement_id is not None]
    assert len(movements) == 6, "trois sorties et leurs trois inverses"
    assert len(reversals) == 3, "un inverse par ligne, pas un de plus"
    assert restored == [Decimal("100.000")] * 3, "le stock doit être revenu à l'identique"
    assert costs == [Decimal("10.0000")] * 3, "le CMP ne bouge pas : on rend au coût de sortie"


def test_t15_second_cancellation_violates_the_reversal_uniqueness(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """T15 — une seconde annulation viole `inv_reversal_uq`, sans mouvement de plus."""
    sale_id, product_ids, _ = _confirmed_sale(session_factory, tenant_a, lines=1)
    product_id = product_ids[0]

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        origin = movements_for_sale(session, tenant_a, sale_id)[0]
        reverse(session, tenant_a, origin)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        before = count_movements(session, product_id)

    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        reverse(session, tenant_a, origin)

    assert sqlstate(excinfo.value) == _UNIQUE_VIOLATION
    assert constraint_name(excinfo.value) == "inv_reversal_uq"

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        after = count_movements(session, product_id)
        stock = read_stock(session, product_id)

    assert after == before, "la seconde annulation ne doit laisser aucune trace"
    assert stock.qty_on_hand == Decimal("100.000"), "le stock ne doit pas être rendu deux fois"


def test_t16_reversing_a_reversal_is_refused(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """T16 — annuler une annulation lève l'exception de `inv_check_reversal`."""
    sale_id, _, _ = _confirmed_sale(session_factory, tenant_a, lines=1)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        origin = movements_for_sale(session, tenant_a, sale_id)[0]
        reverse(session, tenant_a, origin)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        reversal = next(
            row
            for row in movements_for_sale(session, tenant_a, sale_id)
            if row.reversal_of_movement_id is not None
        )

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        reverse(session, tenant_a, reversal, movement_type="sale_out")

    assert "annuler une annulation" in str(excinfo.value)


def test_t17_two_movements_for_the_same_line_violate_the_idempotence_index(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """T17 — deux sorties pour la même `sale_item` violent `inv_ref_idempotence`.

    C'est cet index partiel, et lui seul, qui rend une confirmation rejouée
    inoffensive : le stock ne peut pas être sorti deux fois pour une même ligne.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "100", unit_cost="10")
        sale_id = make_sale(session, tenant_a)
        item_id = add_line(session, tenant_a, sale_id, product_id, qty="4", unit_price="1500")
        sale_out(session, tenant_a, product_id, item_id, "4")

    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        sale_out(session, tenant_a, product_id, item_id, "4")

    assert sqlstate(excinfo.value) == _UNIQUE_VIOLATION
    assert constraint_name(excinfo.value) == "inv_ref_idempotence"

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        assert count_movements(session, product_id) == 2, "l'initial et une seule sortie"
        assert read_stock(session, product_id).qty_on_hand == Decimal("96.000")
