"""Corps des événements émis par Finance.

Deux des neuf types de la V1 : `payment.received` et `debt.created`. `debt.settled`
viendra avec les allocations, en phase 07.
"""

from __future__ import annotations

from datetime import date
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


def debt_created_payload(
    *,
    debt_id: UUID,
    customer_id: UUID,
    principal: Decimal,
    sale_id: UUID | None,
    due_date: date | None,
) -> dict[str, str | None]:
    """Corps de `debt.created`."""
    return {
        "debt_id": str(debt_id),
        "customer_id": str(customer_id),
        "principal": serialize(principal),
        "sale_id": None if sale_id is None else str(sale_id),
        "due_date": None if due_date is None else due_date.isoformat(),
    }
