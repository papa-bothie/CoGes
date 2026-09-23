"""Liste **fermée** des événements métier de CoGes.

Notation pointée `namespace.action`. Ajouter un type est une décision à faire
valider : la liste est verrouillée à trois endroits — cette énumération, un `CHECK`
sur `business_events.event_type`, et un test qui refuse tout nom hors liste.
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """Les neuf événements métier de la V1."""

    SALE_CONFIRMED = "sale.confirmed"
    SALE_CANCELLED = "sale.cancelled"
    SALE_RETURNED = "sale.returned"
    SALE_RETURN_REFUNDED = "sale_return.refunded"
    STOCK_UPDATED = "stock.updated"
    PAYMENT_RECEIVED = "payment.received"
    DEBT_CREATED = "debt.created"
    DEBT_SETTLED = "debt.settled"
    EXPENSE_CREATED = "expense.created"


#: Utilisé par la migration et par les tests : une seule source pour les neuf valeurs.
EVENT_TYPES: tuple[str, ...] = tuple(event.value for event in EventType)
