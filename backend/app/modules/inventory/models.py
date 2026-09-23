"""Modèles du module Inventory. Privés : aucun autre module ne les importe.

Deux tables aux statuts opposés :

* `inventory_movements` est la **source de vérité**, append-only. Elle ne se corrige
  pas : on lui ajoute un mouvement inverse ou un ajustement.
* `product_stock` est une **projection**, maintenue par le trigger `t20_inv_apply`.
  Aucun code applicatif ne l'écrit (§ 5.6) — pas même ce module.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Computed, DateTime, Numeric, Text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import NOW, IdentifiedTenantBase, TenantBase

#: L'ENUM `movement_type` est créé par la révision 0001, pas par l'ORM
#: (`create_type=False`). Déclaré ici pour que psycopg envoie le bon type : sans
#: lui, PostgreSQL refuse un `character varying` sur une colonne ENUM.
MOVEMENT_TYPE = PG_ENUM(
    "initial",
    "purchase_in",
    "sale_out",
    "customer_return_in",
    "supplier_return_out",
    "adjustment",
    "loss",
    name="movement_type",
    create_type=False,
)


class InventoryMovement(IdentifiedTenantBase):
    """Une ligne du journal de stock. Écrite une fois, jamais modifiée."""

    __tablename__ = "inventory_movements"

    product_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(MOVEMENT_TYPE)
    qty_delta: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    #: Entrée : coût d'acquisition fourni. Sortie : estampillé au CMP par le
    #: trigger. Inverse : coût du mouvement d'origine (§ 4.8).
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    ref_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    reversal_of_movement_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Date **métier** du mouvement, qui fixe l'ordre canonique du recalcul (§ 5.7).
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


class ProductStock(TenantBase):
    """Projection du journal. La clé primaire est le produit, pas un `id` propre.

    Elle n'hérite donc pas d'`IdentifiedTenantBase`, et son repository ne peut pas
    s'appuyer sur `TenantRepository`, qui suppose une colonne `id`.
    """

    __tablename__ = "product_stock"

    product_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    qty_on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 3), server_default="0")
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), server_default="0")
    #: Colonne générée par PostgreSQL : l'ORM la lit, ne l'écrit jamais.
    stock_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), Computed("round(qty_on_hand * avg_cost, 2)", persisted=True)
    )
    last_movement_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recomputed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
