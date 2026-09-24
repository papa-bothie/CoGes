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

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import (
    BusinessRuleError,
    CogesError,
    NotFoundError,
    ValidationFailedError,
    constraint_name,
    sqlstate,
)
from app.core.events.outbox import emit
from app.core.events.types import EventType
from app.core.tenancy import TenantContext
from app.modules.customers import service as customers_service
from app.modules.finance.events import (
    DEBT_AGGREGATE,
    PAYMENT_AGGREGATE,
    debt_created_payload,
    debt_settled_payload,
    payment_received_payload,
)
from app.modules.finance.models import Debt, Payment, PaymentAllocation, SaleReturnRefund
from app.modules.finance.repository import (
    DebtRepository,
    PaymentAllocationRepository,
    PaymentRepository,
    SaleReturnRefundRepository,
)
from app.modules.finance.schemas import (
    OFFSET_METHOD,
    AllocationInput,
    AllocationRead,
    DebtCreate,
    DebtDetail,
    PaymentCreate,
    PaymentDetail,
    PaymentMethod,
    RefundMethod,
)
from app.modules.suppliers import service as suppliers_service

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


class DebtAlreadyClosedError(BusinessRuleError):
    code = "debt_already_closed"
    default_message = "Cette dette est soldée ou abandonnée : elle ne reçoit plus de règlement."


class AllocationDirectionMismatchError(BusinessRuleError):
    """Sens financier incompatible avec la nature de la dette.

    Ni le § 8.7 ni le § 5.5 ne posent cette règle, et `allocation_check` ne regarde
    pas `direction` — la compensation de l'ADR 0024 en dépend. Elle reste donc
    **applicative** : on ne durcit pas la base sur une contrainte que les documents
    n'écrivent pas. Elle n'en est pas moins vraie : une créance client s'éteint
    quand de l'argent entre, une dette fournisseur quand de l'argent sort.
    """

    code = "allocation_direction_mismatch"
    default_message = (
        "Sens du paiement incompatible : une créance client s'éteint par un encaissement, "
        "une dette fournisseur par un décaissement."
    )


class PaymentReferenceTakenError(BusinessRuleError):
    code = "payment_reference_taken"
    default_message = "Un paiement porte déjà cette référence."


class AllocationsExceedPaymentError(ValidationFailedError):
    """Somme des affectations supérieure au versement.

    422 et non 409 : la requête se contredit elle-même, sans qu'il soit besoin de
    lire l'état de la moindre dette.
    """

    code = "allocations_exceed_payment"
    default_message = "La somme des affectations dépasse le montant du paiement."


class DuplicateAllocationError(ValidationFailedError):
    code = "duplicate_allocation"
    default_message = "La même dette apparaît deux fois dans les affectations."


#: Clés étrangères composites du § 8.6 dont la violation ne peut venir que d'un
#: identifiant inexistant — ou appartenant à une autre entreprise, ce qui revient
#: au même du point de vue du client (404, jamais 403).
#:
#: Ce détour par la contrainte remplace un contrôle applicatif impossible : Sales
#: et Expenses sont **au-dessus** de Finance dans l'ordre des dépendances, Finance
#: ne peut donc pas leur demander si la pièce existe.
_FK_NOT_FOUND: dict[str, str] = {
    "payments_sale_fk": "Vente introuvable.",
    "payments_expense_fk": "Dépense introuvable.",
    "debts_sale_fk": "Vente introuvable.",
    "debts_expense_fk": "Dépense introuvable.",
    "debts_customer_fk": "Client introuvable.",
    "debts_supplier_fk": "Fournisseur introuvable.",
    "pa_debt_fk": "Dette introuvable.",
}

#: Contraintes d'unicité traduites en refus nommés.
_UNIQUE_ERRORS: dict[str, type[BusinessRuleError]] = {
    "payments_ref_uq": PaymentReferenceTakenError,
}


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


def _translate(exc: DBAPIError, *, details: dict[str, Any]) -> CogesError | None:
    """Traduit un refus de PostgreSQL en erreur nommée, ou rend None.

    Trois familles, dans cet ordre : les SQLSTATE applicatifs des triggers, les
    clés étrangères composites (une pièce qui n'existe pas, ou pas ici), et les
    unicités. Le texte du message n'est jamais lu — seuls le SQLSTATE et le nom de
    la contrainte sont stables (ADR 0014).
    """
    trigger_error = _TRIGGER_ERRORS.get(sqlstate(exc) or "")
    if trigger_error is not None:
        return trigger_error(details=details)

    name = constraint_name(exc) or ""
    missing = _FK_NOT_FOUND.get(name)
    if missing is not None:
        return NotFoundError(missing, details=details)

    unique_error = _UNIQUE_ERRORS.get(name)
    if unique_error is not None:
        return unique_error(details=details)
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
        named_error = _translate(exc, details=details)
        if named_error is None:
            raise
        raise named_error from exc
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
            party_type=debt.party_type,
            customer_id=customer_id,
            supplier_id=None,
            principal=debt.principal,
            sale_id=debt.sale_id,
            expense_id=None,
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


# ------------------------------------------- écritures autonomes (phase 07)

#: Sens d'un versement qui éteint la dette de chaque partie. Une créance client
#: se solde quand de l'argent **entre** ; une dette fournisseur quand il **sort**.
_SETTLING_DIRECTION: dict[str, str] = {"customer": "inflow", "supplier": "outflow"}


def _allocation_total(allocations: Sequence[AllocationInput]) -> Decimal:
    return sum((item.amount for item in allocations), Decimal("0"))


def _allocate(
    session: Session,
    ctx: TenantContext,
    payment: Payment,
    allocations: Sequence[AllocationInput],
) -> list[Debt]:
    """Impute un versement sur des dettes, dans l'ordre de leurs identifiants.

    L'ordre n'est pas cosmétique : deux versements affectant les deux mêmes dettes
    en sens inverse s'interbloqueraient. Trier par `id` donne à toutes les
    transactions la même séquence de verrous — la discipline déjà tenue par
    `confirm_sale` sur les lignes de vente.

    Chaque dette est lue `FOR UPDATE` **avant** d'être comparée à l'affectation.
    Le trigger `pa_check` reprend ce verrou et reste l'autorité ; le contrôle
    applicatif ne sert qu'à nommer le solde dans le refus (ADR 0014).
    """
    repository = DebtRepository(session, ctx)
    allocation_repository = PaymentAllocationRepository(session, ctx)
    settled: list[Debt] = []

    for item in sorted(allocations, key=lambda entry: entry.debt_id):
        debt = repository.get_for_update(item.debt_id)
        if debt is None:
            raise NotFoundError("Dette introuvable.", details={"debt_id": str(item.debt_id)})

        details: dict[str, Any] = {
            "debt_id": str(debt.id),
            "balance": str(debt.balance),
            "requested": str(item.amount),
        }
        if debt.status in ("paid", "written_off"):
            raise DebtAlreadyClosedError(details={**details, "status": debt.status})
        if payment.direction != _SETTLING_DIRECTION[debt.party_type]:
            raise AllocationDirectionMismatchError(
                details={**details, "party_type": debt.party_type, "direction": payment.direction}
            )
        if item.amount > debt.balance:
            raise AllocationExceedsBalanceError(details=details)

        allocation = allocation_repository.add(
            PaymentAllocation(
                company_id=ctx.company_id,
                payment_id=payment.id,
                debt_id=debt.id,
                amount=item.amount,
            )
        )
        _flush(session, allocation, details=details)

        # `pa_rollup` vient de réécrire `amount_paid`, `status` et `closed_at` :
        # l'objet en mémoire est périmé tant qu'on ne le relit pas.
        session.refresh(debt)
        if debt.status == "paid":
            settled.append(debt)

    return settled


def record_payment(
    session: Session,
    ctx: TenantContext,
    payload: PaymentCreate,
    *,
    ip_address: str | None = None,
) -> Payment:
    """Enregistre un encaissement ou un décaissement, et l'impute (Diagramme 5).

    L'ordre est celui du diagramme : cohérence de la demande, paiement, lettrages
    sous verrou, soldes recalculés par trigger, dettes soldées annoncées, audit
    critique, outbox. La clé d'idempotence, première étape du diagramme, est posée
    **avant** par le router — elle appartient au transport, pas à la règle.

    Le sur-paiement est refusé : la somme des affectations ne peut dépasser ni le
    versement (422, la demande se contredit) ni le solde de chaque dette (409,
    l'état refuse). Aucun avoir, aucun solde créditeur en V1.
    """
    debt_ids = [item.debt_id for item in payload.allocations]
    if len(set(debt_ids)) != len(debt_ids):
        raise DuplicateAllocationError(details={"debt_ids": [str(value) for value in debt_ids]})

    allocated = _allocation_total(payload.allocations)
    if allocated > payload.amount:
        raise AllocationsExceedPaymentError(
            details={"allocated": str(allocated), "amount": str(payload.amount)}
        )

    payment = PaymentRepository(session, ctx).add(
        Payment(
            company_id=ctx.company_id,
            direction=payload.direction,
            method=payload.method,
            amount=payload.amount,
            sale_id=payload.sale_id,
            expense_id=payload.expense_id,
            reference=payload.reference,
            note=payload.note,
            created_by=ctx.user_id,
        )
    )
    if payload.paid_at is not None:
        # Sans date saisie, on laisse le `DEFAULT now()` de PostgreSQL : affecter
        # `None` enverrait un NULL sur une colonne qui n'en accepte pas.
        payment.paid_at = payload.paid_at
    _flush(session, payment, details={"amount": str(payload.amount)})

    settled = _allocate(session, ctx, payment, payload.allocations)

    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT,
        entity_table="payments",
        entity_id=payment.id,
        after={
            **_audited_payment(payment),
            "allocations": [
                {"debt_id": str(item.debt_id), "amount": str(item.amount)}
                for item in payload.allocations
            ],
        },
        ip_address=ip_address,
    )

    if payment.direction == "inflow":
        # Aucun `payment.sent` dans la liste fermée des neuf événements : un
        # décaissement n'émet rien plutôt que de se faire passer pour une recette
        # (ADR 0026, décision 3).
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

    for debt in settled:
        emit(
            session,
            ctx,
            event_type=EventType.DEBT_SETTLED,
            aggregate_type=DEBT_AGGREGATE,
            aggregate_id=debt.id,
            payload=debt_settled_payload(
                debt_id=debt.id,
                party_type=debt.party_type,
                customer_id=debt.customer_id,
                supplier_id=debt.supplier_id,
                principal=debt.principal,
                payment_id=payment.id,
                closed_at=debt.closed_at,
            ),
        )
    return payment


def create_debt(
    session: Session,
    ctx: TenantContext,
    payload: DebtCreate,
    *,
    ip_address: str | None = None,
) -> Debt:
    """Ouvre une dette à la main : engagement fournisseur, ou créance hors vente.

    Le tiers est vérifié par sa façade — Customers et Suppliers sont **sous**
    Finance, elle a le droit de les interroger. La pièce d'origine facultative
    (`expense_id`), elle, appartient à un module situé **au-dessus** : c'est la clé
    étrangère composite qui la valide, et sa violation ressort en 404.
    """
    details: dict[str, Any] = {
        "party_type": payload.party_type,
        "principal": str(payload.principal),
    }

    if payload.party_type == "customer" and payload.customer_id is not None:
        customers_service.assert_exists(session, ctx, payload.customer_id)
        limit = customers_service.get_credit_limit(session, ctx, payload.customer_id)
        outstanding = DebtRepository(session, ctx).open_balance_for_customer(payload.customer_id)
        details |= {
            "customer_id": str(payload.customer_id),
            "outstanding": str(outstanding),
            "credit_limit": None if limit is None else str(limit),
        }
        if limit is not None and outstanding + payload.principal > limit:
            raise CreditLimitExceededError(details=details)
    elif payload.supplier_id is not None:
        suppliers_service.assert_exists(session, ctx, payload.supplier_id)
        details["supplier_id"] = str(payload.supplier_id)

    debt = DebtRepository(session, ctx).add(
        Debt(
            company_id=ctx.company_id,
            party_type=payload.party_type,
            customer_id=payload.customer_id,
            supplier_id=payload.supplier_id,
            expense_id=payload.expense_id,
            principal=payload.principal,
            amount_paid=Decimal("0"),
            due_date=payload.due_date,
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
            party_type=debt.party_type,
            customer_id=debt.customer_id,
            supplier_id=debt.supplier_id,
            principal=debt.principal,
            sale_id=debt.sale_id,
            expense_id=debt.expense_id,
            due_date=debt.due_date,
        ),
    )
    return debt


def write_off_debt(
    session: Session,
    ctx: TenantContext,
    debt_id: UUID,
    *,
    reason: str,
    ip_address: str | None = None,
) -> Debt:
    """Abandonne une créance : renonciation à un actif, donc audit critique.

    `principal` n'est **jamais** réécrit (§ 5.5) : la dette est close, pas effacée,
    et son reste dû reste lisible. `closed_at` est renseigné, sans quoi le `CHECK`
    `debts_closed_coherent` refuserait le statut.

    Une dette déjà partiellement réglée **est** abandonnable, contrairement à
    `write_off_sale_debt` : renoncer au reliquat d'un client qui a payé la moitié
    puis disparu est le cas réel. L'autre fonction sert l'annulation d'une vente,
    où de l'argent reçu doit d'abord être rendu — deux gestes, deux règles.

    Aucun événement : `debt.settled` dirait qu'elle a été réglée. Elle ne l'a pas été.
    """
    debt = DebtRepository(session, ctx).get_for_update(debt_id)
    if debt is None:
        raise NotFoundError("Dette introuvable.")
    if debt.status in ("paid", "written_off"):
        raise DebtAlreadyClosedError(details={"debt_id": str(debt.id), "status": debt.status})

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


# ---------------------------------------------- lectures paginées (phase 07)


def get_debt(session: Session, ctx: TenantContext, debt_id: UUID) -> Debt:
    """Dette du tenant courant. Celle d'une autre entreprise donne 404."""
    debt = DebtRepository(session, ctx).get(debt_id)
    if debt is None:
        raise NotFoundError("Dette introuvable.")
    return debt


def list_payments(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    direction: str | None = None,
    period_from: datetime | None = None,
    period_to: datetime | None = None,
) -> tuple[Sequence[Payment], int]:
    repository = PaymentRepository(session, ctx)
    items = repository.page_filtered(
        page=page,
        page_size=page_size,
        direction=direction,
        period_from=period_from,
        period_to=period_to,
    )
    total = repository.count_filtered(
        direction=direction, period_from=period_from, period_to=period_to
    )
    return items, total


def list_debts(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    party_type: str | None = None,
    status: str | None = None,
    overdue: bool = False,
) -> tuple[Sequence[Debt], int]:
    """Page de dettes. `overdue` borne sur aujourd'hui, pas sur une date saisie."""
    repository = DebtRepository(session, ctx)
    overdue_on = datetime.now(UTC).date() if overdue else None
    items = repository.page_filtered(
        page=page,
        page_size=page_size,
        party_type=party_type,
        status=status,
        overdue_on=overdue_on,
    )
    total = repository.count_filtered(party_type=party_type, status=status, overdue_on=overdue_on)
    return items, total


def allocations_of_payments(
    session: Session, ctx: TenantContext, payment_ids: Sequence[UUID]
) -> dict[UUID, list[PaymentAllocation]]:
    """Affectations d'un lot de versements, groupées — une requête, pas N."""
    grouped: dict[UUID, list[PaymentAllocation]] = {}
    for allocation in PaymentAllocationRepository(session, ctx).for_payments(payment_ids):
        grouped.setdefault(allocation.payment_id, []).append(allocation)
    return grouped


def allocations_of_debts(
    session: Session, ctx: TenantContext, debt_ids: Sequence[UUID]
) -> dict[UUID, list[PaymentAllocation]]:
    """Règlements reçus par un lot de dettes, groupés."""
    grouped: dict[UUID, list[PaymentAllocation]] = {}
    for allocation in PaymentAllocationRepository(session, ctx).for_debts(debt_ids):
        grouped.setdefault(allocation.debt_id, []).append(allocation)
    return grouped


def build_payment_detail(
    payment: Payment, allocations: Sequence[PaymentAllocation]
) -> PaymentDetail:
    """Vue publique d'un paiement, ses affectations comprises."""
    return PaymentDetail(
        id=payment.id,
        direction=payment.direction,
        method=payment.method,
        amount=payment.amount,
        paid_at=payment.paid_at,
        sale_id=payment.sale_id,
        expense_id=payment.expense_id,
        sale_return_id=payment.sale_return_id,
        reference=payment.reference,
        note=payment.note,
        created_at=payment.created_at,
        allocations=[AllocationRead.model_validate(item) for item in allocations],
    )


def build_debt_detail(debt: Debt, allocations: Sequence[PaymentAllocation]) -> DebtDetail:
    """Vue publique d'une dette, ses règlements compris."""
    return DebtDetail(
        id=debt.id,
        party_type=debt.party_type,
        customer_id=debt.customer_id,
        supplier_id=debt.supplier_id,
        sale_id=debt.sale_id,
        expense_id=debt.expense_id,
        principal=debt.principal,
        amount_paid=debt.amount_paid,
        balance=debt.balance,
        due_date=debt.due_date,
        status=debt.status,
        closed_at=debt.closed_at,
        created_at=debt.created_at,
        allocations=[AllocationRead.model_validate(item) for item in allocations],
    )


# ------------------------------------- façades de restitution (bande E)


def cash_summary(
    session: Session, ctx: TenantContext, *, period_from: datetime, period_to: datetime
) -> dict[str, Decimal]:
    """Encaissé et décaissé de la période, compensations exclues (ADR 0024)."""
    return PaymentRepository(session, ctx).cash_totals(period_from=period_from, period_to=period_to)


def daily_cash(
    session: Session,
    ctx: TenantContext,
    *,
    period_from: datetime,
    period_to: datetime,
    timezone: str,
) -> list[tuple[date, str, Decimal]]:
    """Série jour × sens, dans le fuseau de l'entreprise."""
    rows = PaymentRepository(session, ctx).daily_cash(
        period_from=period_from, period_to=period_to, timezone=timezone
    )
    return [(row[0], row[1], Decimal(row[2])) for row in rows]


def open_debt_totals(session: Session, ctx: TenantContext) -> dict[str, Decimal]:
    """Créances clients et dettes fournisseurs encore ouvertes, à l'instant t."""
    return DebtRepository(session, ctx).open_totals_by_party()
