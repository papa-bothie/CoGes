"""T13 — le journal ne se modifie ni ne s'efface.

L'autorité, ce sont les triggers `inv_no_update` et `inv_no_delete`, qui lèvent
`restrict_violation` — le SQLSTATE que le § 10 exige mot pour mot. Ils tiennent
face à **n'importe quel** rôle, y compris le propriétaire, là où un `REVOKE`
cesserait de protéger dès qu'un rôle privilégié entre en scène. Ce fichier le
prouve deux fois : avec `coges_app`, puis avec le propriétaire.

Pourquoi ne pas retirer en plus le privilège UPDATE à `coges_app`, comme sur
`audit_logs` ? Parce que `SELECT … FOR SHARE` l'exige : `inv_check_reversal()` ne
pourrait plus verrouiller le mouvement qu'il annule, et aucune annulation ne
passerait (ADR 0018). Le DELETE, lui, n'a jamais été accordé — le test le vérifie.

`FORCE ROW LEVEL SECURITY` s'appliquant aussi au propriétaire, le contexte tenant
est posé comme partout ailleurs.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.errors import sqlstate
from app.core.tenancy import SET_TENANT_CONTEXT_SQL, tenant_transaction
from tests.integration.stock_harness import insert_movement, make_product
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: `restrict_violation`, exigé mot pour mot par le § 10 du Modèle de données.
RESTRICT_VIOLATION = "23001"
INSUFFICIENT_PRIVILEGE = "42501"


@pytest.fixture
def movement_id(session_factory: sessionmaker[Any], tenant_a: Tenant) -> UUID:
    """Un mouvement bien réel, qu'on va tenter d'altérer."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        return insert_movement(session, tenant_a, product_id, "initial", "10", unit_cost="10")


def test_t13_update_is_refused_by_the_trigger_in_the_application_role(
    session_factory: sessionmaker[Any], tenant_a: Tenant, movement_id: UUID
) -> None:
    """En `coges_app`, l'UPDATE atteint le trigger et lève `restrict_violation`."""
    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text("UPDATE inventory_movements SET note = 'falsifié' WHERE id = :id"),
            {"id": movement_id},
        )

    assert sqlstate(excinfo.value) == RESTRICT_VIOLATION
    assert "append-only" in str(excinfo.value)


def test_t13_delete_is_out_of_reach_of_the_application_role(
    session_factory: sessionmaker[Any], tenant_a: Tenant, movement_id: UUID
) -> None:
    """Le DELETE n'a jamais été accordé : il s'arrête avant même le trigger.

    Le SQLSTATE diffère donc de celui du § 10 (`restrict_violation`) — non par
    faiblesse, mais parce qu'une barrière **supplémentaire** intervient plus tôt.
    Le test suivant montre le trigger à l'œuvre sur un rôle qui, lui, a le droit.
    """
    with (
        pytest.raises(ProgrammingError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(text("DELETE FROM inventory_movements WHERE id = :id"), {"id": movement_id})

    assert sqlstate(excinfo.value) == INSUFFICIENT_PRIVILEGE


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE inventory_movements SET note = 'falsifié' WHERE id = :id",
        "DELETE FROM inventory_movements WHERE id = :id",
    ],
    ids=["update", "delete"],
)
def test_t13_triggers_refuse_even_a_privileged_role(
    owner_engine: Engine, tenant_a: Tenant, movement_id: UUID, statement: str
) -> None:
    """Avec le rôle propriétaire, qui détient les droits : `restrict_violation`."""
    with pytest.raises(DBAPIError) as excinfo, owner_engine.begin() as connection:
        connection.execute(SET_TENANT_CONTEXT_SQL, {"company_id": str(tenant_a.company_id)})
        connection.execute(text(statement), {"id": movement_id})

    assert sqlstate(excinfo.value) == RESTRICT_VIOLATION
    assert "append-only" in str(excinfo.value)
