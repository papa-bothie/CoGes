"""Qui écoute quoi. Le seul endroit où un événement est relié à une tâche.

Déclaratif et sans import de tâche : les abonnements sont des **noms** de tâches, ce
qui évite tout cycle d'import entre le bus, l'application Celery et les tâches. Un
test vérifie que chaque valeur d'`EventType` figure ici et que chaque nom déclaré
correspond à une tâche réellement enregistrée — un abonnement fantôme perdrait
silencieusement des événements.

Aucune notation d'événement nouvelle : la liste des neuf types reste fermée.
"""

from __future__ import annotations

from app.core.events.types import EventType

#: Reconstruction des faits : les trois événements qui changent le contenu d'une
#: journée de vente. `sold_at` figure dans les trois corps, jamais `cancelled_at` ni
#: `returned_at` — les retours sont rattachés au jour de la vente (§ 4.10).
REBUILD_SALE_DAY = "analytics.rebuild_sale_day"

#: Invalidation seule, pour les faits qui déplacent le tableau de bord sans toucher à
#: `daily_sales_facts` : trésorerie, créances, stock.
INVALIDATE_DASHBOARD = "analytics.invalidate_dashboard"

ON_STOCK_UPDATED = "notifications.on_stock_updated"
ON_SALE_CANCELLED = "notifications.on_sale_cancelled"

#: Un abonnement par type, sans exception. Un type sans abonné serait écrit dans
#: l'outbox, publié, puis perdu — la forme de panne la plus difficile à voir.
SUBSCRIPTIONS: dict[EventType, tuple[str, ...]] = {
    EventType.SALE_CONFIRMED: (REBUILD_SALE_DAY,),
    EventType.SALE_CANCELLED: (REBUILD_SALE_DAY, ON_SALE_CANCELLED),
    EventType.SALE_RETURNED: (REBUILD_SALE_DAY,),
    EventType.SALE_RETURN_REFUNDED: (INVALIDATE_DASHBOARD,),
    EventType.STOCK_UPDATED: (ON_STOCK_UPDATED, INVALIDATE_DASHBOARD),
    EventType.PAYMENT_RECEIVED: (INVALIDATE_DASHBOARD,),
    EventType.DEBT_CREATED: (INVALIDATE_DASHBOARD,),
    EventType.DEBT_SETTLED: (INVALIDATE_DASHBOARD,),
    EventType.EXPENSE_CREATED: (INVALIDATE_DASHBOARD,),
}


def subscribers(event_type: EventType) -> tuple[str, ...]:
    """Tâches abonnées à ce type d'événement."""
    return SUBSCRIPTIONS[event_type]
