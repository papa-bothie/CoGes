"""Corps des événements émis par Finance.

Quatre des dix types de la V1 : `payment.received`, `payment.cancelled`,
`debt.created` et `debt.settled`. La liste est **fermée** (ADR 0008) — et elle ne contient pas de
`payment.sent` : un décaissement n'émet donc rien, plutôt que d'emprunter le nom
d'un encaissement pour dire le contraire de ce qui s'est passé (ADR 0026).

Un abandon de créance n'émet rien non plus : `debt.settled` dirait qu'elle a été
réglée. L'audit critique, lui, en garde la trace avec son motif.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.core.money import serialize

PAYMENT_AGGREGATE = "payment"
DEBT_AGGREGATE = "debt"


def payment_received_payload(
    *,
    payment_id: UUID,
    amount: Decimal,
    method: str,
    sale_id: UUID | None,
) -> dict[str, str | None]:
    """Corps de `payment.received`, tel que les abonnés de la phase 08 le liront."""
    return {
        "payment_id": str(payment_id),
        "amount": serialize(amount),
        "method": method,
        "sale_id": None if sale_id is None else str(sale_id),
    }


def payment_cancelled_payload(
    *,
    payment_id: UUID,
    cancellation_id: UUID,
    direction: str,
    method: str,
    amount: Decimal,
    sale_id: UUID | None,
    debt_ids: list[UUID],
    sale_return_ids: list[UUID],
) -> dict[str, str | list[str] | None]:
    """Corps de `payment.cancelled` (ADR 0038).

    `direction` est celle du paiement **annulé**, pas de sa contre-écriture : c'est le
    fait que l'abonné cherche. Les dettes et retours dont le solde est revenu en
    arrière sont nommés, pour qu'aucun abonné n'ait à relire les lettrages.
    """
    return {
        "payment_id": str(payment_id),
        "cancellation_id": str(cancellation_id),
        "direction": direction,
        "method": method,
        "amount": serialize(amount),
        "sale_id": None if sale_id is None else str(sale_id),
        "debt_ids": [str(value) for value in debt_ids],
        "sale_return_ids": [str(value) for value in sale_return_ids],
    }


def debt_created_payload(
    *,
    debt_id: UUID,
    party_type: str,
    customer_id: UUID | None,
    supplier_id: UUID | None,
    principal: Decimal,
    sale_id: UUID | None,
    expense_id: UUID | None,
    due_date: date | None,
) -> dict[str, str | None]:
    """Corps de `debt.created`, pour une créance client comme pour une dette fournisseur.

    `party_type` évite à un abonné d'avoir à deviner le sens de l'engagement en
    regardant lequel des deux identifiants est nul.
    """
    return {
        "debt_id": str(debt_id),
        "party_type": party_type,
        "customer_id": None if customer_id is None else str(customer_id),
        "supplier_id": None if supplier_id is None else str(supplier_id),
        "principal": serialize(principal),
        "sale_id": None if sale_id is None else str(sale_id),
        "expense_id": None if expense_id is None else str(expense_id),
        "due_date": None if due_date is None else due_date.isoformat(),
    }


def debt_settled_payload(
    *,
    debt_id: UUID,
    party_type: str,
    customer_id: UUID | None,
    supplier_id: UUID | None,
    principal: Decimal,
    payment_id: UUID,
    closed_at: datetime | None,
) -> dict[str, str | None]:
    """Corps de `debt.settled` : la dette est éteinte, et par quel versement."""
    return {
        "debt_id": str(debt_id),
        "party_type": party_type,
        "customer_id": None if customer_id is None else str(customer_id),
        "supplier_id": None if supplier_id is None else str(supplier_id),
        "principal": serialize(principal),
        "payment_id": str(payment_id),
        "closed_at": None if closed_at is None else closed_at.isoformat(),
    }
