"""Modèles du module Products. Privés : aucun autre module ne les importe.

`products` ne porte **ni prix, ni coût, ni stock** : ce sont des faits datés. Le
prix vit dans `product_prices` par intervalles, le stock dans le journal
`inventory_movements` (phase 04). Aucune notion de variante non plus (§ 2.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import NOW, IdentifiedTenantBase


class Product(IdentifiedTenantBase):
    """Fiche produit : ce qui ne change pas d'un jour à l'autre."""

    __tablename__ = "products"

    category_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    sku: Mapped[str] = mapped_column(Text)
    barcode: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    is_stock_tracked: Mapped[bool] = mapped_column(Boolean)
    #: Taux appliqué **par défaut** à la saisie d'une vente. Jamais relu ensuite :
    #: la ligne de vente fige son propre taux à la confirmation (§ 4.2).
    default_tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    reorder_point: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductPrice(IdentifiedTenantBase):
    """Un intervalle de tarification, fermé par le suivant.

    L'intervalle courant est celui dont `valid_to` est NULL. `product_prices` n'a
    pas d'`updated_at` : une ligne ne se corrige pas, elle se ferme.
    """

    __tablename__ = "product_prices"

    product_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
