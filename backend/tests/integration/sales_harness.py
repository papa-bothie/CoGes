"""Outils communs aux tests d'intégrité des ventes (T14 à T17, T23, T24, T39).

Tout passe par du SQL brut exécuté en `coges_app`, jamais par l'API ni par le
service : « un test qui passerait parce que l'API a vérifié quelque chose ne vaut
rien » (§ 10 du Modèle de données). Les fonctions ci-dessous posent des `INSERT` et
relisent des lignes — aucune règle métier n'y est réimplémentée, à commencer par les
totaux, dont la seule formule vit dans `sale_recompute_totals` et les colonnes
générées.

L'ordre de `confirm_sale` n'est pas cosmétique : `sale_items_no_change` refuse
d'écrire une ligne sur une vente qui n'est plus `draft` (ADR 0023). On garnit donc
le brouillon, puis on le confirme — comme le fait le service.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from tests.tenancy.harness import Tenant

_INSERT_SALE = text(
    """
    INSERT INTO sales (id, company_id, customer_id, sale_no, created_by)
    VALUES (:id, :company_id, :customer_id, :sale_no, :created_by)
    """
)

_INSERT_ITEM = text(
    """
    INSERT INTO sale_items
        (id, company_id, sale_id, product_id, qty, unit_price, unit_cost, discount, tax_rate)
    VALUES (:id, :company_id, :sale_id, :product_id,
            :qty, :unit_price, :unit_cost, :discount, :tax_rate)
    """
)

_CONFIRM_SALE = text(
    """
    UPDATE sales SET status = 'confirmed', confirmed_at = now()
     WHERE company_id = :company_id AND id = :id
    """
)

_CANCEL_SALE = text(
    """
    UPDATE sales SET status = 'cancelled', cancelled_at = now(), cancel_reason = :reason
     WHERE company_id = :company_id AND id = :id
    """
)

_SALE_OUT = text(
    """
    INSERT INTO inventory_movements
        (id, company_id, product_id, type, qty_delta, unit_cost, ref_type, ref_id, created_by)
    VALUES (:id, :company_id, :product_id, 'sale_out', :qty_delta, 0,
            'sale_item', :sale_item_id, :created_by)
    """
)

_REVERSE = text(
    """
    INSERT INTO inventory_movements
        (id, company_id, product_id, type, qty_delta, unit_cost,
         reversal_of_movement_id, created_by)
    VALUES (:id, :company_id, :product_id, :type, :qty_delta, :unit_cost,
            :origin_id, :created_by)
    """
)

_READ_SALE = text(
    """
    SELECT status, subtotal, discount_total, tax_total, total, paid_total, cancel_reason
      FROM sales WHERE id = :sale_id
    """
)

_READ_ITEMS = text(
    """
    SELECT id, product_id, qty, unit_price, unit_cost, discount,
           tax_rate, net_amount, tax_amount, line_total
      FROM sale_items WHERE sale_id = :sale_id ORDER BY created_at, id
    """
)

_MOVEMENTS_FOR_SALE = text(
    """
    SELECT m.id, m.product_id, m.qty_delta, m.unit_cost, m.reversal_of_movement_id
      FROM inventory_movements m
      JOIN sale_items i ON i.id = m.ref_id
     WHERE m.company_id = :company_id AND m.ref_type = 'sale_item' AND i.sale_id = :sale_id
     ORDER BY m.created_at, m.id
    """
)


def make_sale(session: Session, tenant: Tenant, *, customer_id: UUID | None = None) -> UUID:
    """Un brouillon de vente, propre à un test."""
    sale_id = uuid4()
    session.execute(
        _INSERT_SALE,
        {
            "id": sale_id,
            "company_id": tenant.company_id,
            "customer_id": customer_id,
            "sale_no": f"V-{sale_id.hex[:6].upper()}",
            "created_by": tenant.user_id,
        },
    )
    return sale_id


def add_line(
    session: Session,
    tenant: Tenant,
    sale_id: UUID,
    product_id: UUID,
    *,
    qty: str = "1",
    unit_price: str = "1000",
    unit_cost: str = "0",
    discount: str = "0",
    tax_rate: str = "0",
) -> UUID:
    """Une ligne écrite directement en SQL. La vente doit être en brouillon."""
    item_id = uuid4()
    session.execute(
        _INSERT_ITEM,
        {
            "id": item_id,
            "company_id": tenant.company_id,
            "sale_id": sale_id,
            "product_id": product_id,
            "qty": Decimal(qty),
            "unit_price": Decimal(unit_price),
            "unit_cost": Decimal(unit_cost),
            "discount": Decimal(discount),
            "tax_rate": Decimal(tax_rate),
        },
    )
    return item_id


def confirm(session: Session, tenant: Tenant, sale_id: UUID) -> None:
    """Passe la vente en `confirmed`, sans toucher au stock."""
    session.execute(_CONFIRM_SALE, {"company_id": tenant.company_id, "id": sale_id})


def cancel(
    session: Session, tenant: Tenant, sale_id: UUID, reason: str = "Erreur de saisie"
) -> None:
    """Passe la vente en `cancelled`, sans toucher au stock."""
    session.execute(
        _CANCEL_SALE, {"company_id": tenant.company_id, "id": sale_id, "reason": reason}
    )


def sale_out(
    session: Session, tenant: Tenant, product_id: UUID, sale_item_id: UUID, qty: str
) -> UUID:
    """Sortie de stock d'une ligne de vente. `qty` est la quantité **vendue**."""
    movement_id = uuid4()
    session.execute(
        _SALE_OUT,
        {
            "id": movement_id,
            "company_id": tenant.company_id,
            "product_id": product_id,
            "qty_delta": -Decimal(qty),
            "sale_item_id": sale_item_id,
            "created_by": tenant.user_id,
        },
    )
    return movement_id


def reverse(
    session: Session,
    tenant: Tenant,
    origin: Any,
    *,
    movement_type: str = "customer_return_in",
) -> UUID:
    """Mouvement inverse d'une sortie de vente.

    `unit_cost`, `ref_type` et `ref_id` sont de toute façon réécrits par
    `t10_inv_check_reversal` depuis l'origine : on les envoie par politesse.
    """
    movement_id = uuid4()
    session.execute(
        _REVERSE,
        {
            "id": movement_id,
            "company_id": tenant.company_id,
            "product_id": origin.product_id,
            "type": movement_type,
            "qty_delta": -origin.qty_delta,
            "unit_cost": origin.unit_cost,
            "origin_id": origin.id,
            "created_by": tenant.user_id,
        },
    )
    return movement_id


def read_sale(session: Session, sale_id: UUID) -> Any:
    """En-tête de vente, totaux compris."""
    return session.execute(_READ_SALE, {"sale_id": sale_id}).one()


def read_items(session: Session, sale_id: UUID) -> Any:
    """Lignes d'une vente, montants générés compris."""
    return session.execute(_READ_ITEMS, {"sale_id": sale_id}).all()


def movements_for_sale(session: Session, tenant: Tenant, sale_id: UUID) -> Any:
    """Tous les mouvements rattachés aux lignes d'une vente, inverses compris."""
    return session.execute(
        _MOVEMENTS_FOR_SALE, {"company_id": tenant.company_id, "sale_id": sale_id}
    ).all()
