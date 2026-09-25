"""Liste **fermée** des événements métier de CoGes.

Notation pointée `namespace.action`. Ajouter un type est une décision à faire
valider : la liste est verrouillée à trois endroits — cette énumération, un `CHECK`
sur `business_events.event_type`, et un test qui refuse tout nom hors liste.
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """Les dix événements métier de la V1.

    `payment.cancelled`, le dixième, a été validé en phase 10 (ADR 0038) : sans lui,
    l'annulation d'un paiement laisserait le tableau de bord faux jusqu'à l'expiration
    de son cache.
    """

    SALE_CONFIRMED = "sale.confirmed"
    SALE_CANCELLED = "sale.cancelled"
    SALE_RETURNED = "sale.returned"
    SALE_RETURN_REFUNDED = "sale_return.refunded"
    STOCK_UPDATED = "stock.updated"
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_CANCELLED = "payment.cancelled"
    DEBT_CREATED = "debt.created"
    DEBT_SETTLED = "debt.settled"
    EXPENSE_CREATED = "expense.created"


#: Utilisé par la migration et par les tests : une seule source pour les dix valeurs.
EVENT_TYPES: tuple[str, ...] = tuple(event.value for event in EventType)
