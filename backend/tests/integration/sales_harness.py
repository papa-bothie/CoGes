"""Outils communs aux tests d'intégrité des ventes (T14 à T24, T39).

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


_INSERT_RETURN = text(
    """
    INSERT INTO sale_returns (id, company_id, sale_id, return_no, reason, created_by)
    VALUES (:id, :company_id, :sale_id, :return_no, :reason, :created_by)
    """
)

_INSERT_RETURN_ITEM = text(
    """
    INSERT INTO sale_return_items
        (id, company_id, return_id, sale_item_id, qty, refund_amount, tax_refund, unit_cost)
    VALUES (:id, :company_id, :return_id, :sale_item_id,
            :qty, :refund_amount, :tax_refund, :unit_cost)
    """
)

_RETURN_IN = text(
    """
    INSERT INTO inventory_movements
        (id, company_id, product_id, type, qty_delta, unit_cost, ref_type, ref_id, created_by)
    VALUES (:id, :company_id, :product_id, 'customer_return_in', :qty, :unit_cost,
            'sale_return_item', :return_item_id, :created_by)
    """
)

_INSERT_REFUND_PAYMENT = text(
    """
    INSERT INTO payments
        (id, company_id, direction, method, amount, sale_return_id, created_by)
    VALUES (:id, :company_id, CAST(:direction AS cash_direction), CAST(:method AS pay_method),
            :amount, :sale_return_id, :created_by)
    """
)

_INSERT_REFUND = text(
    """
    INSERT INTO sale_return_refunds (id, company_id, sale_return_id, payment_id, amount)
    VALUES (:id, :company_id, :sale_return_id, :payment_id, :amount)
    """
)

_READ_RETURN = text(
    """
    SELECT return_no, returned_at, total_refund, refunded_total, refund_status
      FROM sale_returns WHERE id = :return_id
    """
)


def make_return(
    session: Session, tenant: Tenant, sale_id: UUID, *, reason: str | None = None
) -> UUID:
    """Un en-tête de retour. La vente doit être confirmée."""
    return_id = uuid4()
    session.execute(
        _INSERT_RETURN,
        {
            "id": return_id,
            "company_id": tenant.company_id,
            "sale_id": sale_id,
            "return_no": f"R-{return_id.hex[:6].upper()}",
            "reason": reason,
            "created_by": tenant.user_id,
        },
    )
    return return_id


def return_line(
    session: Session,
    tenant: Tenant,
    return_id: UUID,
    sale_item_id: UUID,
    *,
    qty: str,
    refund_amount: str = "0",
    tax_refund: str = "0",
    unit_cost: str = "0",
) -> UUID:
    """Une ligne de retour. C'est ici que `sri_check` borne le cumul retourné."""
    item_id = uuid4()
    session.execute(
        _INSERT_RETURN_ITEM,
        {
            "id": item_id,
            "company_id": tenant.company_id,
            "return_id": return_id,
            "sale_item_id": sale_item_id,
            "qty": Decimal(qty),
            "refund_amount": Decimal(refund_amount),
            "tax_refund": Decimal(tax_refund),
            "unit_cost": Decimal(unit_cost),
        },
    )
    return item_id


def return_in(
    session: Session,
    tenant: Tenant,
    product_id: UUID,
    return_item_id: UUID,
    *,
    qty: str,
    unit_cost: str,
) -> UUID:
    """Rentrée de stock d'une ligne de retour, **sans** `reversal_of_movement_id`."""
    movement_id = uuid4()
    session.execute(
        _RETURN_IN,
        {
            "id": movement_id,
            "company_id": tenant.company_id,
            "product_id": product_id,
            "qty": Decimal(qty),
            "unit_cost": Decimal(unit_cost),
            "return_item_id": return_item_id,
            "created_by": tenant.user_id,
        },
    )
    return movement_id


def refund_payment(
    session: Session,
    tenant: Tenant,
    return_id: UUID | None,
    *,
    amount: str,
    direction: str = "outflow",
    method: str = "cash",
) -> UUID:
    """Un décaissement rattaché à un retour. `direction` est paramétrable pour T21."""
    payment_id = uuid4()
    session.execute(
        _INSERT_REFUND_PAYMENT,
        {
            "id": payment_id,
            "company_id": tenant.company_id,
            "direction": direction,
            "method": method,
            "amount": Decimal(amount),
            "sale_return_id": return_id,
            "created_by": tenant.user_id,
        },
    )
    return payment_id


def letter_refund(
    session: Session, tenant: Tenant, return_id: UUID, payment_id: UUID, *, amount: str
) -> UUID:
    """Lettrage retour ↔ paiement. C'est ici que `refund_check` arbitre."""
    refund_id = uuid4()
    session.execute(
        _INSERT_REFUND,
        {
            "id": refund_id,
            "company_id": tenant.company_id,
            "sale_return_id": return_id,
            "payment_id": payment_id,
            "amount": Decimal(amount),
        },
    )
    return refund_id


def read_return(session: Session, return_id: UUID) -> Any:
    """En-tête d'un retour : totaux et statut, tous maintenus par trigger."""
    return session.execute(_READ_RETURN, {"return_id": return_id}).one()


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
