"""Corps de l'événement émis par Expenses.

Un seul des neuf types de la V1 : `expense.created`. Une modification ou une
suppression de dépense n'émet rien — la liste est fermée (ADR 0008), et l'audit
critique, lui, garde la trace des deux.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from app.core.money import serialize

EXPENSE_AGGREGATE = "expense"


def expense_created_payload(
    *,
    expense_id: UUID,
    expense_no: str,
    category_id: UUID,
    kind: str,
    amount: Decimal,
    spent_at: date,
) -> dict[str, str | None]:
    """Corps de `expense.created`, tel que les abonnés de la phase 08 le liront.

    `kind` y figure bien qu'il vive sur la catégorie : l'analytique ventile les
    charges fixes et variables sans avoir à relire `expense_categories`.
    """
    return {
        "expense_id": str(expense_id),
        "expense_no": expense_no,
        "category_id": str(category_id),
        "kind": kind,
        "amount": serialize(amount),
        "spent_at": spent_at.isoformat(),
    }
