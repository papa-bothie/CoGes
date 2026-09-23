"""Événement `stock.updated` émis par Inventory.

Écrit dans l'outbox **à l'intérieur** de la transaction métier, publié seulement
après COMMIT (Diagramme 6) : jamais d'alerte de stock pour un mouvement annulé par
rollback, jamais de mouvement sans son événement.

Les décimaux partent en **chaînes** : un consommateur qui relirait un flottant
recalculerait une valeur de stock fausse.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.core.money import serialize

#: Agrégat désigné par l'événement. Le stock se raisonne par produit, pas par
#: mouvement : un abonné qui déduplique le fait sur le produit.
AGGREGATE_TYPE = "product"


def stock_updated_payload(
    *,
    product_id: UUID,
    qty_on_hand: Decimal,
    avg_cost: Decimal,
    movement_id: UUID,
    below_reorder_point: bool,
) -> dict[str, str | bool]:
    """Corps de `stock.updated`, tel que les abonnés de la phase 08 le liront."""
    return {
        "product_id": str(product_id),
        "qty_on_hand": serialize(qty_on_hand),
        "avg_cost": serialize(avg_cost),
        "movement_id": str(movement_id),
        "below_reorder_point": below_reorder_point,
    }
