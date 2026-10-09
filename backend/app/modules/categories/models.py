"""Modèles du module Categories. Privés : aucun autre module ne les importe."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import NOW, IdentifiedTenantBase


class Category(IdentifiedTenantBase):
    """Nœud de l'arbre de classification.

    L'arbre est porté par `parent_id`, validé par la FK **composite**
    `categories_self_fk (company_id, parent_id)` : le parent appartient
    nécessairement à la même entreprise, indépendamment de la RLS.
    """

    __tablename__ = "categories"

    parent_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(Text)
    #: Couleur du rayon, de 1 à 8 (révision 0017, ADR 0071) ; vide = tirée du nom.
    color: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
