"""Corps des événements émis par Sales.

Deux des neuf types de la V1 : `sale.confirmed` et `sale.cancelled`. `sale.returned`
viendra avec les retours, en phase 06.

Ces corps sont le contrat de la phase 08. Ils portent assez pour reconstruire
`daily_sales_facts` sans relire la vente : un abonné qui doit requêter la base pour
comprendre un événement n'est plus découplé de l'émetteur.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.money import serialize

AGGREGATE_TYPE = "sale"


def confirmed_line_payload(
    *,
    sale_item_id: UUID,
    product_id: UUID,
    qty: Decimal,
    unit_price: Decimal,
    unit_cost: Decimal,
    net_amount: Decimal,
    tax_amount: Decimal,
) -> dict[str, str]:
    """Une ligne, telle qu'elle entre dans `sale.confirmed`."""
    return {
        "sale_item_id": str(sale_item_id),
        "product_id": str(product_id),
        "qty": serialize(qty),
        "unit_price": serialize(unit_price),
        "unit_cost": serialize(unit_cost),
        "net_amount": serialize(net_amount),
        "tax_amount": serialize(tax_amount),
    }


def sale_confirmed_payload(
    *,
    sale_id: UUID,
    sale_no: str,
    customer_id: UUID | None,
    sold_at: datetime,
    subtotal: Decimal,
    discount_total: Decimal,
    tax_total: Decimal,
    total: Decimal,
    paid_total: Decimal,
    lines: list[dict[str, str]],
) -> dict[str, Any]:
    """Corps de `sale.confirmed`."""
    return {
        "sale_id": str(sale_id),
        "sale_no": sale_no,
        "customer_id": None if customer_id is None else str(customer_id),
        "sold_at": sold_at.isoformat(),
        "subtotal": serialize(subtotal),
        "discount_total": serialize(discount_total),
        "tax_total": serialize(tax_total),
        "total": serialize(total),
        "paid_total": serialize(paid_total),
        "lines": lines,
    }


def sale_cancelled_payload(
    *,
    sale_id: UUID,
    sale_no: str,
    sold_at: datetime,
    total: Decimal,
    reason: str,
    reversed_movement_ids: list[UUID],
) -> dict[str, Any]:
    """Corps de `sale.cancelled`.

    `sold_at` et non `cancelled_at` en tête : l'analytique réécrit le jour de la
    **vente**, pas celui de l'annulation (§ 12.1 point 3).
    """
    return {
        "sale_id": str(sale_id),
        "sale_no": sale_no,
        "sold_at": sold_at.isoformat(),
        "total": serialize(total),
        "reason": reason,
        "reversed_movement_ids": [str(movement_id) for movement_id in reversed_movement_ids],
    }
