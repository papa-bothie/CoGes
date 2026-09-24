"""T25 à T28 — le cycle de vie d'une dette, mesuré **dans la base**.

Ces quatre tests n'appellent aucune route. Ils écrivent dans `debts`,
`payments` et `payment_allocations` avec le rôle applicatif, sous RLS, et vérifient
ce que PostgreSQL a fait de ces écritures. C'est l'exigence du § 10 : « un test qui
passerait parce que l'API a vérifié quelque chose ne vaut rien ».

Ce qui est mesuré ici n'est donc pas le service de la phase 07, mais les trois
mécanismes qui le tiennent :

* `pa_rollup`, qui recalcule `amount_paid`, `status` et `closed_at` après chaque
  lettrage — le service n'écrit **jamais** ces trois colonnes ;
* `balance`, colonne **générée** `principal - amount_paid`, donc impossible à
  contredire ;
* `allocation_check`, qui refuse une affectation supérieure au solde ou au reste
  disponible du versement.

T28 a déjà son fichier, consacré à la concurrence (`test_t28_concurrent_credit_limit`).
Le cas simple — une dette qui dépasse le plafond, sans rien de simultané — manquait :
il est ici, parce que la règle doit tenir avant même qu'on parle de concurrence.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.errors import sqlstate
from app.core.tenancy import tenant_transaction
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: SQLSTATE applicatifs des refus financiers (révisions 0007 et 0008, ADR 0026).
CREDIT_LIMIT_EXCEEDED = "CG030"
ALLOCATION_EXCEEDS_BALANCE = "CG044"
PAYMENT_OVER_ALLOCATED = "CG045"


def _customer(
    session_factory: sessionmaker[Any], tenant: Tenant, *, credit_limit: str | None = None
) -> UUID:
    """Un client neuf. Ceux du harnais sont partagés entre les tests."""
    customer_id = uuid4()
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO customers (id, company_id, code, name, credit_limit) "
                "VALUES (:id, :company_id, :code, :name, :credit_limit)"
            ),
            {
                "id": customer_id,
                "company_id": tenant.company_id,
                "code": f"CLI-{customer_id.hex[:8]}",
                "name": f"Client {customer_id.hex[:6]}",
                "credit_limit": None if credit_limit is None else Decimal(credit_limit),
            },
        )
    return customer_id


def _debt(
    session_factory: sessionmaker[Any],
    tenant: Tenant,
    customer_id: UUID,
    *,
    principal: str,
) -> UUID:
    """Une créance client ouverte, du montant demandé."""
    debt_id = uuid4()
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO debts (id, company_id, party_type, customer_id, principal) "
                "VALUES (:id, :company_id, 'customer', :customer_id, :principal)"
            ),
            {
                "id": debt_id,
                "company_id": tenant.company_id,
                "customer_id": customer_id,
                "principal": Decimal(principal),
            },
        )
    return debt_id


def _payment(session_factory: sessionmaker[Any], tenant: Tenant, *, amount: str) -> UUID:
    """Un encaissement, entièrement disponible pour des lettrages."""
    payment_id = uuid4()
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO payments "
                "(id, company_id, direction, method, amount, created_by) "
                "VALUES (:id, :company_id, 'inflow', 'cash', :amount, :created_by)"
            ),
            {
                "id": payment_id,
                "company_id": tenant.company_id,
                "amount": Decimal(amount),
                "created_by": tenant.user_id,
            },
        )
    return payment_id


def _allocate(session: Any, tenant: Tenant, payment_id: UUID, debt_id: UUID, amount: str) -> None:
    session.execute(
        text(
            "INSERT INTO payment_allocations (company_id, payment_id, debt_id, amount) "
            "VALUES (:company_id, :payment_id, :debt_id, :amount)"
        ),
        {
            "company_id": tenant.company_id,
            "payment_id": payment_id,
            "debt_id": debt_id,
            "amount": Decimal(amount),
        },
    )


def _debt_state(
    session_factory: sessionmaker[Any], tenant: Tenant, debt_id: UUID
) -> tuple[Decimal, Decimal, str, Any]:
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        row = session.execute(
            text("SELECT amount_paid, balance, status, closed_at FROM debts  WHERE id = :id"),
            {"id": debt_id},
        ).one()
    return row.amount_paid, row.balance, row.status, row.closed_at


def test_t25_a_partial_payment_leaves_the_debt_partially_paid(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Dette 1 000, affectation 400 ⇒ payé 400, solde 600, statut `partially_paid`.

    Rien de tout cela n'est écrit : `amount_paid` et `status` viennent de
    `pa_rollup`, et `balance` est une colonne générée.
    """
    customer_id = _customer(session_factory, tenant_a)
    debt_id = _debt(session_factory, tenant_a, customer_id, principal="1000.00")
    payment_id = _payment(session_factory, tenant_a, amount="400.00")

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        _allocate(session, tenant_a, payment_id, debt_id, "400.00")

    amount_paid, balance, status, closed_at = _debt_state(session_factory, tenant_a, debt_id)
    assert amount_paid == Decimal("400.00")
    assert balance == Decimal("600.00")
    assert status == "partially_paid"
    assert closed_at is None, "une dette encore due n'est pas close"


def test_t26_a_payment_cannot_be_split_beyond_its_own_amount(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Versement 1 000 réparti 400 / 400 / 300 : la troisième affectation lève.

    Le refus vient de la seconde vérification d'`allocation_check` — le reste
    disponible du **versement**, pas le solde des dettes, qui sont assez grandes.
    Les deux premières affectations tiennent : seule la troisième est annulée.
    """
    customer_id = _customer(session_factory, tenant_a)
    debts = [_debt(session_factory, tenant_a, customer_id, principal="1000.00") for _ in range(3)]
    payment_id = _payment(session_factory, tenant_a, amount="1000.00")

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        _allocate(session, tenant_a, payment_id, debts[0], "400.00")
        _allocate(session, tenant_a, payment_id, debts[1], "400.00")

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        _allocate(session, tenant_a, payment_id, debts[2], "300.00")

    assert sqlstate(excinfo.value) == PAYMENT_OVER_ALLOCATED, str(excinfo.value)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        allocated = session.execute(
            text(
                "SELECT coalesce(sum(amount), 0) FROM payment_allocations  WHERE payment_id = :id"
            ),
            {"id": payment_id},
        ).scalar_one()
    assert allocated == Decimal("800.00"), "la troisième affectation n'a rien laissé"


def test_t26_an_allocation_cannot_exceed_the_balance_of_its_debt(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """L'autre moitié d'`allocation_check` : le solde de la dette, non le versement.

    Deux refus distincts, deux SQLSTATE distincts (`CG044` et `CG045`, ADR 0026) :
    sans cela, un caissier ne saurait pas s'il a trop encaissé ou mal réparti.
    """
    customer_id = _customer(session_factory, tenant_a)
    debt_id = _debt(session_factory, tenant_a, customer_id, principal="500.00")
    payment_id = _payment(session_factory, tenant_a, amount="1000.00")

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        _allocate(session, tenant_a, payment_id, debt_id, "600.00")

    assert sqlstate(excinfo.value) == ALLOCATION_EXCEEDS_BALANCE, str(excinfo.value)


def test_t27_a_debt_reaching_zero_is_paid_and_closed(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Solde à 0 ⇒ statut `paid` et `closed_at` renseigné, en deux versements.

    Deux versements plutôt qu'un : c'est le passage par `partially_paid` puis par
    `paid` qui prouve que `pa_rollup` recalcule, et ne se contente pas de poser un
    statut à la création.
    """
    customer_id = _customer(session_factory, tenant_a)
    debt_id = _debt(session_factory, tenant_a, customer_id, principal="1000.00")
    # Les deux versements sont créés **avant** : le pool de la suite ne compte
    # qu'une connexion (T4), et ouvrir une transaction dans une autre l'épuiserait.
    first = _payment(session_factory, tenant_a, amount="600.00")
    second = _payment(session_factory, tenant_a, amount="400.00")

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        _allocate(session, tenant_a, first, debt_id, "600.00")
    assert _debt_state(session_factory, tenant_a, debt_id)[2] == "partially_paid"

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        _allocate(session, tenant_a, second, debt_id, "400.00")

    amount_paid, balance, status, closed_at = _debt_state(session_factory, tenant_a, debt_id)
    assert amount_paid == Decimal("1000.00")
    assert balance == Decimal("0.00")
    assert status == "paid"
    assert closed_at is not None, "`debts_closed_coherent` exige une date de clôture"


def test_t28_a_debt_beyond_the_credit_limit_is_refused(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Plafond 1 000, encours 800, nouvelle dette de 300 : `debt_credit_limit` lève.

    Le cas simple, sans concurrence. `test_t28_concurrent_credit_limit` couvre
    l'autre moitié de la promesse du § 5.5 — celle qui exige un verrou.
    """
    customer_id = _customer(session_factory, tenant_a, credit_limit="1000.00")
    _debt(session_factory, tenant_a, customer_id, principal="800.00")

    with pytest.raises(DBAPIError) as excinfo:
        _debt(session_factory, tenant_a, customer_id, principal="300.00")

    assert sqlstate(excinfo.value) == CREDIT_LIMIT_EXCEEDED, str(excinfo.value)


def test_t28_a_customer_without_a_limit_is_never_refused(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """`credit_limit` nul = aucun plafond, et non un plafond à zéro.

    La distinction est celle du § 8.7 : `IF v_limit IS NULL THEN RETURN NEW`. La
    confondre fermerait le crédit à tous les clients dont personne n'a fixé
    l'encours — c'est-à-dire, au démarrage, à tout le monde.
    """
    customer_id = _customer(session_factory, tenant_a)
    _debt(session_factory, tenant_a, customer_id, principal="10000000.00")
