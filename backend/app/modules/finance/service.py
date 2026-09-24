"""Façade de services du module Finance.

Finance de gestion, pas comptabilité générale (décision 09). En phase 05, elle ne
répond qu'à Sales, et à trois questions : encaisser une vente, ouvrir la dette de
ce qui reste dû, éteindre cette dette quand la vente est annulée.

Ce que ce module n'écrit **jamais** en Python :

* `sales.paid_total` — maintenu par le trigger `sale_paid_rollup` depuis `payments` ;
* `debts.amount_paid`, `balance` et `status` — maintenus par `pa_rollup` depuis
  `payment_allocations`, et `balance` est une colonne générée.

La phase 06 lui ajoute le remboursement d'un retour, et la compensation d'une dette
par ce remboursement. Les dépenses arrivent en phase 07.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import BusinessRuleError, NotFoundError, sqlstate
from app.core.events.outbox import emit
from app.core.events.types import EventType
from app.core.tenancy import TenantContext
from app.modules.customers import service as customers_service
from app.modules.finance.events import (
    DEBT_AGGREGATE,
    PAYMENT_AGGREGATE,
    debt_created_payload,
    payment_received_payload,
)
from app.modules.finance.models import Debt, Payment, PaymentAllocation, SaleReturnRefund
from app.modules.finance.repository import (
    DebtRepository,
    PaymentAllocationRepository,
    PaymentRepository,
    SaleReturnRefundRepository,
)
from app.modules.finance.schemas import OFFSET_METHOD, PaymentMethod, RefundMethod

# --------------------------------------------------------------- erreurs métier


class CreditLimitExceededError(BusinessRuleError):
    code = "credit_limit_exceeded"
    default_message = "Plafond de crédit dépassé : cette vente à crédit ne peut pas être ouverte."


class CustomerRequiredForCreditError(BusinessRuleError):
    code = "customer_required_for_credit"
    default_message = "Vente à crédit : un client identifié est obligatoire."


class RefundExceedsDueError(BusinessRuleError):
    code = "refund_exceeds_due"
    default_message = "Remboursement supérieur au reste dû de ce retour."


class RefundRequiresOutflowError(BusinessRuleError):
    code = "refund_requires_outflow"
    default_message = (
        "Un remboursement de retour est une sortie : il ne peut pas être un encaissement."
    )


class PaymentOverAllocatedError(BusinessRuleError):
    code = "payment_over_allocated"
    default_message = (
        "Paiement sur-affecté : le montant disponible ne couvre pas cette affectation."
    )


class AllocationExceedsBalanceError(BusinessRuleError):
    code = "allocation_exceeds_balance"
    default_message = "Affectation supérieure au solde restant de la dette."


class DebtPartiallyPaidError(BusinessRuleError):
    code = "debt_partially_paid"
    default_message = (
        "Cette dette a déjà reçu un règlement : elle doit être traitée "
        "financièrement avant que la vente puisse être annulée."
    )


#: SQLSTATE applicatifs levés par les triggers financiers (ADR 0023 et 0026).
#: Sans eux, ces refus arriveraient tous en `check_violation`, indistinguables.
_TRIGGER_ERRORS: dict[str, type[BusinessRuleError]] = {
    "CG030": CreditLimitExceededError,
    "CG041": RefundExceedsDueError,
    "CG042": RefundRequiresOutflowError,
    "CG043": PaymentOverAllocatedError,
    "CG044": AllocationExceedsBalanceError,
    "CG045": PaymentOverAllocatedError,
}


def _translate(exc: DBAPIError, *, details: dict[str, Any]) -> BusinessRuleError | None:
    """Traduit un refus de PostgreSQL en erreur métier, ou rend None."""
    trigger_error = _TRIGGER_ERRORS.get(sqlstate(exc) or "")
    if trigger_error is not None:
        return trigger_error(details=details)
    return None


def _flush(
    session: Session,
    entity: Payment | Debt | PaymentAllocation | SaleReturnRefund,
    *,
    details: dict[str, Any],
) -> None:
    """Pousse l'écriture, traduit le refus éventuel, puis relit la ligne.

    La relecture n'est pas une précaution : `debts.balance` est une colonne
    générée et `status` peut être réécrit par trigger. Sans `refresh`, l'API
    renverrait ce qu'on a envoyé, pas ce que la base a écrit (ADR 0018).
    """
    try:
        session.flush()
    except (IntegrityError, DBAPIError) as exc:
        business_error = _translate(exc, details=details)
        if business_error is None:
            raise
        raise business_error from exc
    session.refresh(entity)


# ------------------------------------------------------------------- lectures


def payments_for_sale(session: Session, ctx: TenantContext, sale_id: UUID) -> list[Payment]:
    """Règlements d'une vente, pour son détail et son reçu."""
    return list(PaymentRepository(session, ctx).for_sale(sale_id))


def debt_for_sale(session: Session, ctx: TenantContext, sale_id: UUID) -> Debt | None:
    """La dette née de cette vente, s'il y en a une."""
    return DebtRepository(session, ctx).for_sale(sale_id)


def has_settled_payment(session: Session, ctx: TenantContext, sale_id: UUID) -> bool:
    """La vente porte-t-elle un encaissement non remboursé ?

    Le § 5.2 refuse l'annulation dans ce cas : de l'argent est entré en caisse, et
    l'effacer d'un trait de plume ferait diverger la trésorerie du réel. La
    correction passe par un retour (phase 06). Tant que les remboursements
    n'existent pas, tout encaissement compte.
    """
    return PaymentRepository(session, ctx).inflow_count_for_sale(sale_id) > 0


def payments_for_return(
    session: Session, ctx: TenantContext, sale_return_id: UUID
) -> list[Payment]:
    """Décaissements rattachés à un retour, pour son détail."""
    return list(PaymentRepository(session, ctx).for_return(sale_return_id))


def refunds_for_return(
    session: Session, ctx: TenantContext, sale_return_id: UUID
) -> list[SaleReturnRefund]:
    """Lettrages d'un retour : « quels remboursements pour ce retour » (§ 5.4)."""
    return list(SaleReturnRefundRepository(session, ctx).for_return(sale_return_id))


def refunds_for_payment(
    session: Session, ctx: TenantContext, payment_id: UUID
) -> list[SaleReturnRefund]:
    """Lettrages d'un paiement : « quel retour a provoqué cette sortie » (§ 5.4)."""
    return list(SaleReturnRefundRepository(session, ctx).for_payment(payment_id))


def get_payment(session: Session, ctx: TenantContext, payment_id: UUID) -> Payment:
    """Paiement du tenant courant. Celui d'une autre entreprise donne 404."""
    payment = PaymentRepository(session, ctx).get(payment_id)
    if payment is None:
        raise NotFoundError("Paiement introuvable.")
    return payment


def open_debt_for_sale(session: Session, ctx: TenantContext, sale_id: UUID) -> Debt | None:
    """La dette encore vivante née de cette vente, verrouillée.

    Verrouillée parce que la compensation qui suit va la réduire : sans ce verrou,
    deux retours concurrents liraient le même solde et l'épuiseraient deux fois. Le
    trigger `allocation_check` prend le même verrou — celui-ci ne fait que l'avancer
    pour que le refus applicatif parle du bon chiffre.
    """
    debt = DebtRepository(session, ctx).get_open_for_sale_for_update(sale_id)
    return debt


# ------------------------------------------------------------------- écritures


def record_sale_payment(
    session: Session,
    ctx: TenantContext,
    *,
    sale_id: UUID,
    amount: Decimal,
    method: PaymentMethod,
    ip_address: str | None = None,
) -> Payment:
    """Encaisse la part réglée d'une vente (§ 5.1 étape 7).

    Paiement **direct** : `sale_id` renseigné, sans dette ni allocation (§ 5.5).
    `sales.paid_total` est recalculé par `sale_paid_rollup` ; rien n'est écrit ici.
    """
    payment = PaymentRepository(session, ctx).add(
        Payment(
            company_id=ctx.company_id,
            direction="inflow",
            method=method,
            amount=amount,
            sale_id=sale_id,
            created_by=ctx.user_id,
        )
    )
    _flush(session, payment, details={"sale_id": str(sale_id)})

    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT,
        entity_table="payments",
        entity_id=payment.id,
        after=_audited_payment(payment),
        ip_address=ip_address,
    )
    emit(
        session,
        ctx,
        event_type=EventType.PAYMENT_RECEIVED,
        aggregate_type=PAYMENT_AGGREGATE,
        aggregate_id=payment.id,
        payload=payment_received_payload(
            payment_id=payment.id,
            amount=payment.amount,
            method=payment.method,
            sale_id=payment.sale_id,
        ),
    )
    return payment


def open_customer_debt(
    session: Session,
    ctx: TenantContext,
    *,
    sale_id: UUID,
    customer_id: UUID | None,
    principal: Decimal,
    due_date: date | None = None,
    ip_address: str | None = None,
) -> Debt:
    """Ouvre la dette du solde impayé d'une vente (§ 5.1 étape 7).

    Une vente à crédit exige un client identifié : sans nom, il n'y a personne à
    qui réclamer, et le plafond de crédit ne veut plus rien dire.

    Le plafond est vérifié deux fois, à dessein. Ici, pour nommer l'encours, le
    plafond et le montant qui ne passe pas ; et en base, par `debt_credit_limit`,
    qui est l'autorité. Ce contrôle-ci lit sans verrou : sous concurrence, il peut
    laisser passer une demande que le trigger refusera ensuite en `CG030`. C'est
    voulu — le trigger, lui, verrouille la ligne client avant de sommer l'encours
    (révision 0007), et deux caisses qui ouvrent un crédit au même client s'y
    sérialisent. Redondance assumée, dans l'esprit de l'ADR 0014.
    """
    if customer_id is None:
        raise CustomerRequiredForCreditError(details={"sale_id": str(sale_id)})

    repository = DebtRepository(session, ctx)
    limit = customers_service.get_credit_limit(session, ctx, customer_id)
    outstanding = repository.open_balance_for_customer(customer_id)
    details: dict[str, Any] = {
        "customer_id": str(customer_id),
        "requested": str(principal),
        "outstanding": str(outstanding),
        "credit_limit": None if limit is None else str(limit),
    }
    if limit is not None and outstanding + principal > limit:
        raise CreditLimitExceededError(details=details)

    debt = repository.add(
        Debt(
            company_id=ctx.company_id,
            party_type="customer",
            customer_id=customer_id,
            sale_id=sale_id,
            principal=principal,
            amount_paid=Decimal("0"),
            due_date=due_date,
            status="open",
        )
    )
    _flush(session, debt, details=details)

    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT,
        entity_table="debts",
        entity_id=debt.id,
        after=_audited_debt(debt),
        ip_address=ip_address,
    )
    emit(
        session,
        ctx,
        event_type=EventType.DEBT_CREATED,
        aggregate_type=DEBT_AGGREGATE,
        aggregate_id=debt.id,
        payload=debt_created_payload(
            debt_id=debt.id,
            customer_id=customer_id,
            principal=debt.principal,
            sale_id=debt.sale_id,
            due_date=debt.due_date,
        ),
    )
    return debt


def write_off_sale_debt(
    session: Session,
    ctx: TenantContext,
    *,
    sale_id: UUID,
    reason: str,
    ip_address: str | None = None,
) -> Debt | None:
    """Éteint la dette d'une vente annulée (§ 5.2 étape 4), ou ne fait rien.

    `principal` n'est jamais réécrit (§ 5.5) : la dette est close, pas effacée.
    Rend `None` si la vente n'avait pas de dette — une vente payée comptant.

    Une dette déjà partiellement réglée n'est **pas** abandonnable : l'argent reçu
    devrait d'abord être remboursé ou réaffecté. L'appelant l'apprend par le refus,
    pas par un silence.
    """
    debt = DebtRepository(session, ctx).for_sale(sale_id)
    if debt is None:
        return None
    if debt.amount_paid > 0:
        raise DebtPartiallyPaidError(
            details={"debt_id": str(debt.id), "amount_paid": str(debt.amount_paid)}
        )

    before = _audited_debt(debt)
    debt.status = "written_off"
    debt.closed_at = datetime.now(UTC)
    session.flush()
    session.refresh(debt)

    audit_critical(
        session,
        ctx,
        action=AuditAction.CANCEL,
        entity_table="debts",
        entity_id=debt.id,
        before=before,
        after={**_audited_debt(debt), "reason": reason},
        ip_address=ip_address,
    )
    return debt


# -------------------------------------------------------------------- privés


def _audited_payment(payment: Payment) -> dict[str, Any]:
    """Vue d'un paiement pour l'audit : ce qui engage, rien de plus."""
    return {
        "id": str(payment.id),
        "direction": payment.direction,
        "method": payment.method,
        "amount": str(payment.amount),
        "sale_id": None if payment.sale_id is None else str(payment.sale_id),
    }


def _audited_debt(debt: Debt) -> dict[str, Any]:
    """Vue d'une dette pour l'audit."""
    return {
        "id": str(debt.id),
        "customer_id": None if debt.customer_id is None else str(debt.customer_id),
        "principal": str(debt.principal),
        "amount_paid": str(debt.amount_paid),
        "status": debt.status,
        "sale_id": None if debt.sale_id is None else str(debt.sale_id),
    }


def record_return_refund(
    session: Session,
    ctx: TenantContext,
    *,
    sale_return_id: UUID,
    amount: Decimal,
    method: RefundMethod,
    reference: str | None = None,
    note: str | None = None,
    ip_address: str | None = None,
) -> tuple[Payment, SaleReturnRefund]:
    """Rembourse un retour en trésorerie (§ 5.4 étapes 2-3).

    Le paiement porte `direction = 'outflow'` et `sale_return_id` : le CHECK
    `payments_return_outflow` rejette tout encaissement rattaché à un retour (T21),
    et `payments_context_one` interdit qu'il pointe aussi la vente. Le rattachement
    fin passe par le lettrage, qui autorise l'échelonnement et le versement couvrant
    deux retours.

    Aucun événement n'est émis ici. La liste des neuf types de la V1 est fermée et
    n'a pas de `payment.sent` ; `payment.received` dirait le contraire de ce qui se
    passe. C'est `sale_return.refunded`, émis par Sales, qui porte le fait.
    """
    payment = PaymentRepository(session, ctx).add(
        Payment(
            company_id=ctx.company_id,
            direction="outflow",
            method=method,
            amount=amount,
            sale_return_id=sale_return_id,
            reference=reference,
            note=note,
            created_by=ctx.user_id,
        )
    )
    details: dict[str, Any] = {"sale_return_id": str(sale_return_id), "amount": str(amount)}
    _flush(session, payment, details=details)

    refund = SaleReturnRefundRepository(session, ctx).add(
        SaleReturnRefund(
            company_id=ctx.company_id,
            sale_return_id=sale_return_id,
            payment_id=payment.id,
            amount=amount,
        )
    )
    # C'est ce flush-ci que `refund_check` arbitre : reste dû du retour, sens du
    # paiement, et part encore libre du versement. Les trois sous verrou.
    _flush(session, refund, details=details)

    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT,
        entity_table="payments",
        entity_id=payment.id,
        after=_audited_payment(payment),
        ip_address=ip_address,
    )
    return payment, refund


def record_return_offset(
    session: Session,
    ctx: TenantContext,
    *,
    sale_return_id: UUID,
    debt_id: UUID,
    amount: Decimal,
    ip_address: str | None = None,
) -> tuple[Payment, Payment]:
    """Éteint une dette du client par le remboursement qui lui est dû (ADR 0024).

    Le § 4.6 prévoit cette extinction « via `payment_allocations` », sans dire comment
    l'écrire : une allocation exige un paiement, et un paiement lié à un retour doit
    être un `outflow`. Avec les cinq moyens de paiement existants, la compensation
    s'écrirait comme une sortie de caisse qui n'a pas eu lieu, puis une entrée qui n'a
    pas eu lieu non plus.

    D'où **deux** paiements en `offset`, dans la même transaction :

    1. un `outflow` rattaché au retour et lettré dans `sale_return_refunds` — le
       retour est remboursé, `refunded_total` monte, `refund_status` suit ;
    2. un `inflow` **sans contexte**, alloué à la dette — `pa_rollup` recalcule
       `amount_paid`, `status` et `closed_at`.

    L'`inflow` ne porte pas `sale_id`, et ce n'est pas un oubli : `sale_paid_rollup`
    somme les encaissements d'une vente pour en faire `paid_total`, qui doit rester ce
    qui est **encaissé**. Une compensation n'encaisse rien. Le chaînage reste lisible
    par la dette, qui porte déjà `sale_id`.

    Les deux écritures sont marquées `offset` : la trésorerie les exclut, les lettrages
    les gardent.
    """
    details: dict[str, Any] = {
        "sale_return_id": str(sale_return_id),
        "debt_id": str(debt_id),
        "amount": str(amount),
    }

    outflow, _refund = record_return_refund(
        session,
        ctx,
        sale_return_id=sale_return_id,
        amount=amount,
        method=OFFSET_METHOD,
        note="Compensation d'une dette du client",
        ip_address=ip_address,
    )

    inflow = PaymentRepository(session, ctx).add(
        Payment(
            company_id=ctx.company_id,
            direction="inflow",
            method=OFFSET_METHOD,
            amount=amount,
            note="Compensation par un retour",
            created_by=ctx.user_id,
        )
    )
    _flush(session, inflow, details=details)

    allocation = PaymentAllocationRepository(session, ctx).add(
        PaymentAllocation(
            company_id=ctx.company_id,
            payment_id=inflow.id,
            debt_id=debt_id,
            amount=amount,
        )
    )
    _flush(session, allocation, details=details)

    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT,
        entity_table="payment_allocations",
        entity_id=allocation.id,
        after={
            "id": str(allocation.id),
            "debt_id": str(debt_id),
            "payment_id": str(inflow.id),
            "amount": str(amount),
            "sale_return_id": str(sale_return_id),
        },
        ip_address=ip_address,
    )
    return outflow, inflow
