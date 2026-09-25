"""L'annulation d'un paiement sous concurrence (ADR 0038, révision 0012).

Deux promesses que seule la base peut tenir :

* deux annulations simultanées du même paiement : **une seule** passe —
  `payments_reversal_uq` arbitre, le verrou de `payment_reversal_check` sérialise ;
* une annulation et un nouveau paiement simultanés sur la même dette : le solde final
  est **exact**, quel que soit l'ordre — `payment_reversal_rollup` verrouille la dette
  avant de sommer, dans une instruction distincte, et voit donc ce que l'autre a commité.

Comme T38, le test ne court pas après la fenêtre de concurrence : il la **provoque** en
tenant lui-même le verrou que les deux acteurs vont se disputer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.errors import CogesError
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.finance import service as finance_service
from app.modules.finance.schemas import AllocationInput, PaymentCreate
from tests.conftest import DemoCompany

pytestmark = pytest.mark.integration

REASON = "Saisie erronée sous concurrence"


def _ctx(company: DemoCompany) -> TenantContext:
    return TenantContext(user_id=company.manager_id, company_id=company.company_id)


def _open_debt(session_factory: sessionmaker[Any], company: DemoCompany, *, principal: str) -> UUID:
    """Un client neuf et sa créance."""
    customer_id, debt_id = uuid4(), uuid4()
    with tenant_transaction(_ctx(company), session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO customers (id, company_id, code, name) VALUES (:id, :co, :code, :name)"
            ),
            {
                "id": customer_id,
                "co": company.company_id,
                "code": f"CLI-{customer_id.hex[:8]}",
                "name": f"Client concurrent {customer_id.hex[:6]}",
            },
        )
        session.execute(
            text(
                "INSERT INTO debts (id, company_id, party_type, customer_id, principal) "
                "VALUES (:id, :co, 'customer', :customer, :principal)"
            ),
            {
                "id": debt_id,
                "co": company.company_id,
                "customer": customer_id,
                "principal": Decimal(principal),
            },
        )
    return debt_id


def _pay(
    session_factory: sessionmaker[Any], company: DemoCompany, debt_id: UUID, amount: str
) -> UUID:
    ctx = _ctx(company)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        payment = finance_service.record_payment(
            session,
            ctx,
            PaymentCreate(
                direction="inflow",
                method="cash",
                amount=Decimal(amount),
                allocations=[AllocationInput(debt_id=debt_id, amount=Decimal(amount))],
            ),
        )
        return payment.id


def _cancel(session_factory: sessionmaker[Any], company: DemoCompany, payment_id: UUID) -> str:
    ctx = _ctx(company)
    try:
        with tenant_transaction(ctx, session_factory=session_factory) as session:
            finance_service.cancel_payment(session, ctx, payment_id, reason=REASON)
    except CogesError as exc:
        return exc.code
    return "succès"


def _debt_state(
    session_factory: sessionmaker[Any], company: DemoCompany, debt_id: UUID
) -> tuple[Decimal, str]:
    with tenant_transaction(_ctx(company), session_factory=session_factory) as session:
        row = session.execute(
            text("SELECT amount_paid, status FROM debts WHERE id = :id"), {"id": debt_id}
        ).one()
    return Decimal(row[0]), str(row[1])


def test_two_simultaneous_cancellations_only_one_passes(
    concurrent_session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    debt_id = _open_debt(concurrent_session_factory, company_alpha, principal="60000")
    payment_id = _pay(concurrent_session_factory, company_alpha, debt_id, "50000")

    with ThreadPoolExecutor(max_workers=2) as pool:
        with tenant_transaction(
            _ctx(company_alpha), session_factory=concurrent_session_factory
        ) as session:
            # Le test tient le paiement : les deux annulations s'arrêtent exactement
            # là où `payment_reversal_check` prend son verrou.
            session.execute(
                text("SELECT id FROM payments WHERE id = :id FOR UPDATE"), {"id": payment_id}
            )
            futures = [
                pool.submit(_cancel, concurrent_session_factory, company_alpha, payment_id)
                for _ in range(2)
            ]
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == ["payment_already_cancelled", "succès"], outcomes
    with tenant_transaction(
        _ctx(company_alpha), session_factory=concurrent_session_factory
    ) as session:
        reversals = session.execute(
            text("SELECT count(*) FROM payments WHERE reversal_of_payment_id = :id"),
            {"id": payment_id},
        ).scalar_one()
    assert reversals == 1
    assert _debt_state(concurrent_session_factory, company_alpha, debt_id) == (
        Decimal("0.00"),
        "open",
    )


def test_a_cancellation_and_a_new_payment_on_the_same_debt_add_up(
    concurrent_session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    """Dette de 60 000, 50 000 payés. On annule les 50 000 **pendant** qu'un nouveau
    paiement de 10 000 arrive : dans les deux ordres, il reste 10 000 payés."""
    debt_id = _open_debt(concurrent_session_factory, company_alpha, principal="60000")
    erroneous = _pay(concurrent_session_factory, company_alpha, debt_id, "50000")

    def new_payment() -> str:
        try:
            _pay(concurrent_session_factory, company_alpha, debt_id, "10000")
        except CogesError as exc:
            return exc.code
        return "succès"

    with ThreadPoolExecutor(max_workers=2) as pool:
        with tenant_transaction(
            _ctx(company_alpha), session_factory=concurrent_session_factory
        ) as session:
            # Le test tient la dette : l'annulation (dans son trigger AFTER) et le
            # paiement (dans `_allocate`) viennent s'y heurter.
            session.execute(text("SELECT id FROM debts WHERE id = :id FOR UPDATE"), {"id": debt_id})
            futures = [
                pool.submit(_cancel, concurrent_session_factory, company_alpha, erroneous),
                pool.submit(new_payment),
            ]
        outcomes = [future.result() for future in futures]

    assert outcomes == ["succès", "succès"], outcomes
    assert _debt_state(concurrent_session_factory, company_alpha, debt_id) == (
        Decimal("10000.00"),
        "partially_paid",
    )
    with tenant_transaction(
        _ctx(company_alpha), session_factory=concurrent_session_factory
    ) as session:
        balance = session.execute(
            text("SELECT balance FROM debts WHERE id = :id"), {"id": debt_id}
        ).scalar_one()
    assert balance == Decimal("50000.00")
