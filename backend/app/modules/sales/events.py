"""Corps des événements émis par Sales.

Quatre des neuf types de la V1 : `sale.confirmed`, `sale.cancelled`, `sale.returned`
et `sale_return.refunded`.

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

#: Un remboursement est un fait du **retour**, pas de la vente : il peut en survenir
#: plusieurs, des jours après, et l'abonné qui les suit ne relit pas la vente.
RETURN_AGGREGATE_TYPE = "sale_return"


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


def returned_line_payload(
    *,
    return_item_id: UUID,
    sale_item_id: UUID,
    product_id: UUID,
    qty: Decimal,
    refund_amount: Decimal,
    tax_refund: Decimal,
    unit_cost: Decimal,
) -> dict[str, str]:
    """Une ligne rendue, telle qu'elle entre dans `sale.returned`."""
    return {
        "return_item_id": str(return_item_id),
        "sale_item_id": str(sale_item_id),
        "product_id": str(product_id),
        "qty": serialize(qty),
        "refund_amount": serialize(refund_amount),
        "tax_refund": serialize(tax_refund),
        "unit_cost": serialize(unit_cost),
    }


def sale_returned_payload(
    *,
    return_id: UUID,
    return_no: str,
    sale_id: UUID,
    sale_no: str,
    sold_at: datetime,
    returned_at: datetime,
    total_refund: Decimal,
    lines: list[dict[str, str]],
) -> dict[str, Any]:
    """Corps de `sale.returned`.

    `sold_at` y figure à côté de `returned_at` : l'analytique réécrit le jour de la
    **vente**, celui où le chiffre d'affaires a été compté (§ 12.1 point 3). Les
    `unit_cost` des lignes suffisent à recalculer `cogs_returned` sans relire la base.
    """
    return {
        "return_id": str(return_id),
        "return_no": return_no,
        "sale_id": str(sale_id),
        "sale_no": sale_no,
        "sold_at": sold_at.isoformat(),
        "returned_at": returned_at.isoformat(),
        "total_refund": serialize(total_refund),
        "lines": lines,
    }


def sale_return_refunded_payload(
    *,
    return_id: UUID,
    return_no: str,
    sale_id: UUID,
    payment_id: UUID,
    amount: Decimal,
    method: str,
    refunded_total: Decimal,
    total_refund: Decimal,
    refund_status: str,
) -> dict[str, Any]:
    """Corps de `sale_return.refunded`.

    `method` porte `offset` quand le retour a éteint une dette plutôt que vidé une
    caisse : c'est à ce champ que la trésorerie de la phase 08 reconnaîtra une
    écriture sans flux (ADR 0024).
    """
    return {
        "return_id": str(return_id),
        "return_no": return_no,
        "sale_id": str(sale_id),
        "payment_id": str(payment_id),
        "amount": serialize(amount),
        "method": method,
        "refunded_total": serialize(refunded_total),
        "total_refund": serialize(total_refund),
        "refund_status": refund_status,
    }
