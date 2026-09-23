"""Modèles du module Suppliers. Privés : aucun autre module ne les importe."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import NOW, IdentifiedTenantBase


class Supplier(IdentifiedTenantBase):
    """Fournisseur : coordonnées et délai de règlement indicatif."""

    __tablename__ = "suppliers"

    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Indicatif : la V1 ne calcule aucune échéance d'achat (pas de module Achats).
    payment_terms_days: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
