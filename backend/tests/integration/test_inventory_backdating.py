"""Antidatage : la fenêtre de 48 h, en base (ADR 0015, § 12.1 point 2).

Le CMP dépend de l'ordre des mouvements. Un mouvement inséré avec un `occurred_at`
antérieur au dernier mouvement du produit rend le CMP courant différent du CMP
recalculé — c'est inhérent à toute valorisation en coût moyen, et le schéma ne
l'interdit pas de lui-même. Le § 12.1 laissait deux options ; la fenêtre bornée a
été retenue, parce qu'elle s'explique au gérant.

Le trigger porte le préfixe `t05_` pour se déclencher **avant** `t10_` et `t20_` :
inutile de calculer un CMP qu'on va refuser.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.errors import sqlstate
from app.core.tenancy import tenant_transaction
from tests.integration.stock_harness import insert_movement, make_product, read_stock
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: SQLSTATE applicatif de l'antidatage hors fenêtre (migration 0004).
BACKDATED_TOO_FAR = "CG010"


def test_a_first_movement_may_carry_any_date(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Sans mouvement antérieur, rien à désordonner : la reprise d'existant passe."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(
            session,
            tenant_a,
            product_id,
            "initial",
            "10",
            unit_cost="10",
            occurred_at=datetime.now(UTC) - timedelta(days=400),
        )
        assert read_stock(session, product_id).qty_on_hand == 10


def test_backdating_inside_the_window_is_accepted(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """24 h en arrière : la saisie tardive d'une réception de la veille reste possible."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "10", unit_cost="10")
        insert_movement(
            session,
            tenant_a,
            product_id,
            "purchase_in",
            "10",
            unit_cost="20",
            occurred_at=datetime.now(UTC) - timedelta(hours=24),
        )
        assert read_stock(session, product_id).qty_on_hand == 20


def test_backdating_beyond_the_window_is_refused(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """72 h en arrière : refus, avec un SQLSTATE que le service sait traduire."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "10", unit_cost="10")

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        insert_movement(
            session,
            tenant_a,
            product_id,
            "purchase_in",
            "10",
            unit_cost="20",
            occurred_at=datetime.now(UTC) - timedelta(hours=72),
        )

    assert sqlstate(excinfo.value) == BACKDATED_TOO_FAR

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        assert read_stock(session, product_id).qty_on_hand == 10


def test_the_window_is_measured_from_the_last_movement_not_from_now(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Un article dormant depuis un mois accepte une date proche de son dernier mouvement.

    La fenêtre borne le **désordre**, pas l'ancienneté : c'est l'écart avec le
    dernier mouvement qui compte, sinon un inventaire annuel serait impossible.
    """
    last = datetime.now(UTC) - timedelta(days=30)
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(
            session, tenant_a, product_id, "initial", "10", unit_cost="10", occurred_at=last
        )
        insert_movement(
            session,
            tenant_a,
            product_id,
            "purchase_in",
            "5",
            unit_cost="20",
            occurred_at=last - timedelta(hours=12),
        )
        assert read_stock(session, product_id).qty_on_hand == 15


# ------------------------------------------------- borne haute (révision 0005)

#: SQLSTATE applicatif de la date future (migration 0005).
IN_FUTURE = "CG011"


def test_a_movement_dated_in_the_future_is_refused(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Une date future est une faute de frappe, jamais une intention."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        insert_movement(
            session,
            tenant_a,
            product_id,
            "initial",
            "10",
            unit_cost="10",
            occurred_at=datetime.now(UTC) + timedelta(days=365),
        )

    assert sqlstate(excinfo.value) == IN_FUTURE


def test_a_few_minutes_of_clock_drift_are_tolerated(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """La tolérance absorbe l'écart d'horloge entre l'API et PostgreSQL."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(
            session,
            tenant_a,
            product_id,
            "initial",
            "10",
            unit_cost="10",
            occurred_at=datetime.now(UTC) + timedelta(minutes=2),
        )
        assert read_stock(session, product_id).qty_on_hand == 10


def test_a_refused_future_date_does_not_block_the_product(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Le vrai dégât évité : un produit qui n'accepte plus rien.

    Sans la borne haute, une date future devenait le `max(occurred_at)` du produit.
    Tout mouvement ultérieur daté de `now()` tombait à plus de 48 h en arrière et se
    faisait refuser — ventes comprises. Pire, le mouvement **inverse** écrit pour
    corriger la saisie étant lui aussi daté de `now()`, rien ne rattrapait le
    produit : il fallait intervenir en base.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "10", unit_cost="10")

    with (
        pytest.raises(DBAPIError),
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        insert_movement(
            session,
            tenant_a,
            product_id,
            "purchase_in",
            "5",
            unit_cost="10",
            occurred_at=datetime.now(UTC) + timedelta(days=365),
        )

    # Le produit vit toujours : la saisie suivante, datée de maintenant, passe.
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        insert_movement(session, tenant_a, product_id, "purchase_in", "5", unit_cost="10")
        insert_movement(session, tenant_a, product_id, "sale_out", "-3")
        assert read_stock(session, product_id).qty_on_hand == 12
