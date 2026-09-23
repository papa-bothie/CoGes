"""Outils communs aux tests d'intégrité du stock (T6 à T13, T38).

Tout passe par du SQL brut exécuté en `coges_app`, jamais par l'API ni par le
service : « un test qui passerait parce que l'API a vérifié quelque chose ne vaut
rien » (§ 10 du Modèle de données). Les fonctions ci-dessous ne font donc que poser
des `INSERT` et relire des lignes — aucune règle métier n'y est réimplémentée, à
commencer par le CMP, dont la seule formule vit dans `cmp_next_avg`.

Chaque test fabrique **son** produit : les entreprises de test sont partagées à
l'échelle de la session, mais un stock ne se prête pas.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from tests.tenancy.harness import Tenant

_INSERT_PRODUCT = text(
    """
    INSERT INTO products (id, company_id, sku, name, unit, is_stock_tracked, reorder_point)
    VALUES (:id, :company_id, :sku, :name, 'piece', :is_stock_tracked, :reorder_point)
    """
)

_INSERT_MOVEMENT = text(
    """
    INSERT INTO inventory_movements
        (id, company_id, product_id, type, qty_delta, unit_cost, note, occurred_at)
    VALUES (:id, :company_id, :product_id, CAST(:type AS movement_type),
            :qty_delta, :unit_cost, :note, COALESCE(:occurred_at, now()))
    """
)

_READ_STOCK = text(
    """
    SELECT qty_on_hand, avg_cost, stock_value
      FROM product_stock
     WHERE product_id = :product_id
    """
)


_COUNT_MOVEMENTS = text("SELECT count(*) FROM inventory_movements WHERE product_id = :product_id")


def make_product(
    session: Session,
    tenant: Tenant,
    *,
    is_stock_tracked: bool = True,
    reorder_point: Decimal | None = None,
) -> UUID:
    """Un produit neuf, propre à un test."""
    product_id = uuid4()
    marker = product_id.hex[:8]
    session.execute(
        _INSERT_PRODUCT,
        {
            "id": product_id,
            "company_id": tenant.company_id,
            "sku": f"SKU-{marker}",
            "name": f"Article {marker}",
            "is_stock_tracked": is_stock_tracked,
            "reorder_point": reorder_point,
        },
    )
    return product_id


def insert_movement(
    session: Session,
    tenant: Tenant,
    product_id: UUID,
    movement_type: str,
    qty_delta: str,
    *,
    unit_cost: str = "0",
    note: str | None = None,
    occurred_at: datetime | None = None,
) -> UUID:
    """Un mouvement écrit **directement en SQL**, sans passer par le service."""
    movement_id = uuid4()
    session.execute(
        _INSERT_MOVEMENT,
        {
            "id": movement_id,
            "company_id": tenant.company_id,
            "product_id": product_id,
            "type": movement_type,
            "qty_delta": Decimal(qty_delta),
            "unit_cost": Decimal(unit_cost),
            "note": note,
            "occurred_at": occurred_at,
        },
    )
    return movement_id


def read_stock(session: Session, product_id: UUID) -> Any:
    """Ligne de projection, ou `None` si le trigger ne l'a jamais créée."""
    return session.execute(_READ_STOCK, {"product_id": product_id}).one_or_none()


def count_movements(session: Session, product_id: UUID) -> int:
    """Nombre de lignes du journal pour ce produit."""
    return int(session.execute(_COUNT_MOVEMENTS, {"product_id": product_id}).scalar_one())
