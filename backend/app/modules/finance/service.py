"""Façade de services du module Finance.

Finance de gestion, pas comptabilité générale (décision 09). En phase 05, elle ne
répond qu'à Sales, et à trois questions : encaisser une vente, ouvrir la dette de
ce qui reste dû, éteindre cette dette quand la vente est annulée.

Ce que ce module n'écrit **jamais** en Python :

* `sales.paid_total` — maintenu par le trigger `sale_paid_rollup` depuis `payments` ;
* `debts.amount_paid`, `balance` et `status` — maintenus par `pa_rollup` depuis
  `payment_allocations`, et `balance` est une colonne générée.

Les allocations, les dépenses et les remboursements arrivent en phases 06 et 07.
Leurs tables et leurs triggers existent déjà : il n'y aura pas de migration
structurante à écrire pour eux (ADR 0019).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import BusinessRuleError, sqlstate
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
from app.modules.finance.models import Debt, Payment
from app.modules.finance.repository import DebtRepository, PaymentRepository
from app.modules.finance.schemas import PaymentMethod

# --------------------------------------------------------------- erreurs métier


class CreditLimitExceededError(BusinessRuleError):
    code = "credit_limit_exceeded"
    default_message = "Plafond de crédit dépassé : cette vente à crédit ne peut pas être ouverte."


class CustomerRequiredForCreditError(BusinessRuleError):
    code = "customer_required_for_credit"
    default_message = "Vente à crédit : un client identifié est obligatoire."


class DebtPartiallyPaidError(BusinessRuleError):
    code = "debt_partially_paid"
    default_message = (
        "Cette dette a déjà reçu un règlement : elle doit être traitée "
        "financièrement avant que la vente puisse être annulée."
    )


#: SQLSTATE applicatif levé par `debt_credit_limit()` (migration 0006, ADR 0023).
_CREDIT_LIMIT = "CG030"


def _translate(exc: DBAPIError, *, details: dict[str, Any]) -> BusinessRuleError | None:
    """Traduit un refus de PostgreSQL en erreur métier, ou rend None."""
    if sqlstate(exc) == _CREDIT_LIMIT:
        return CreditLimitExceededError(details=details)
    return None


def _flush(session: Session, entity: Payment | Debt, *, details: dict[str, Any]) -> None:
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
