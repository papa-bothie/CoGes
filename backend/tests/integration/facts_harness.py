"""Outils communs aux tests d'agrégation (T29 à T32).

Comme les autres harnais, tout passe par du SQL brut en `coges_app` : le sujet du
test est la **requête de reconstruction**, pas le service qui l'appelle. On construit
donc des ventes et des retours à la main, on lance `rebuild_days`, et on relit les
faits produits.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from tests.integration import sales_harness as sales
from tests.tenancy.harness import Tenant

_INSERT_PRODUCT = text(
    """
    INSERT INTO products (id, company_id, category_id, sku, name, unit)
    VALUES (:id, :company_id, :category_id, :sku, :name, 'piece')
    """
)

_BACKDATE_SALE = text(
    "UPDATE sales SET sold_at = :sold_at WHERE company_id = :company_id AND id = :id"
)

_READ_FACT = text(
    """
    SELECT qty_sold, returned_qty, net_qty_sold, gross_revenue, discount_total,
           tax_total, refund_net_amount, net_revenue, cogs_gross, cogs_returned,
           cogs_net, sale_count, category_id
      FROM daily_sales_facts
     WHERE company_id = :company_id AND day = :day AND product_id = :product_id
    """
)

_READ_DAY = text(
    """
    SELECT product_id, qty_sold, returned_qty, net_qty_sold, gross_revenue,
           discount_total, tax_total, refund_net_amount, net_revenue, cogs_gross,
           cogs_returned, cogs_net, sale_count
      FROM daily_sales_facts
     WHERE company_id = :company_id AND day = :day
     ORDER BY product_id
    """
)


def extra_product(session: Session, tenant: Tenant, sku: str) -> UUID:
    """Un second produit, pour comparer deux lignes de fait côte à côte."""
    product_id = uuid4()
    session.execute(
        _INSERT_PRODUCT,
        {
            "id": product_id,
            "company_id": tenant.company_id,
            "category_id": tenant.category_id,
            "sku": sku,
            "name": f"Produit {sku}",
        },
    )
    return product_id


def backdate(session: Session, tenant: Tenant, sale_id: UUID, sold_at: dt.datetime) -> None:
    """Antidate une vente.

    `sales.sold_at` n'est pas borné — contrairement à `inventory_movements.occurred_at`
    (ADR 0015) — parce que le mouvement de stock, lui, est daté de la confirmation.
    C'est ce qui permet de fabriquer quatre-vingt-dix jours d'historique en un test.
    """
    session.execute(
        _BACKDATE_SALE,
        {"sold_at": sold_at, "company_id": tenant.company_id, "id": sale_id},
    )


def sold_line(
    session: Session,
    tenant: Tenant,
    product_id: UUID,
    *,
    qty: str,
    unit_price: str = "1000",
    unit_cost: str = "600",
    discount: str = "0",
    tax_rate: str = "0.18",
    sold_at: dt.datetime | None = None,
) -> tuple[UUID, UUID]:
    """Une vente confirmée d'une seule ligne. Renvoie `(sale_id, sale_item_id)`."""
    sale_id = sales.make_sale(session, tenant)
    item_id = sales.add_line(
        session,
        tenant,
        sale_id,
        product_id,
        qty=qty,
        unit_price=unit_price,
        unit_cost=unit_cost,
        discount=discount,
        tax_rate=tax_rate,
    )
    sales.confirm(session, tenant, sale_id)
    if sold_at is not None:
        backdate(session, tenant, sale_id, sold_at)
    return sale_id, item_id


def returned(
    session: Session,
    tenant: Tenant,
    sale_id: UUID,
    sale_item_id: UUID,
    *,
    qty: str,
    unit_price: str = "1000",
    tax_rate: str = "0.18",
    unit_cost: str = "600",
) -> UUID:
    """Un retour partiel d'une ligne de vente, montants calculés au prorata.

    Le remboursable est arrondi net et taxe **séparément** (ADR 0026) : on reproduit
    la même arithmétique ici, sinon le test comparerait deux définitions du retour.
    """
    net = (Decimal(qty) * Decimal(unit_price)).quantize(Decimal("0.01"))
    tax = (net * Decimal(tax_rate)).quantize(Decimal("0.01"))
    return_id = sales.make_return(session, tenant, sale_id)
    sales.return_line(
        session,
        tenant,
        return_id,
        sale_item_id,
        qty=qty,
        refund_amount=str(net + tax),
        tax_refund=str(tax),
        unit_cost=unit_cost,
    )
    return return_id


def read_fact(session: Session, tenant: Tenant, day: dt.date, product_id: UUID) -> Any:
    """La ligne de fait d'un jour et d'un produit, ou `None` si elle a été purgée."""
    return session.execute(
        _READ_FACT,
        {"company_id": tenant.company_id, "day": day, "product_id": product_id},
    ).one_or_none()


def read_day(session: Session, tenant: Tenant, day: dt.date) -> Any:
    """Toutes les lignes de fait d'un jour, triées, pour comparer deux passages."""
    return session.execute(_READ_DAY, {"company_id": tenant.company_id, "day": day}).all()
