"""Modèles du module Import/Export. Privés : aucun autre module ne les importe."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.core.database import NOW, IdentifiedTenantBase

#: ENUM de la révision 0013. `create_type=False` : le type existe déjà.
EXPORT_STATUS = PG_ENUM(
    "pending", "ready", "failed", "expired", name="export_status", create_type=False
)
EXPORT_FORMAT = PG_ENUM("csv", "xlsx", name="export_format", create_type=False)


class ExportFile(IdentifiedTenantBase):
    """Export produit par le worker, servi par l'API pendant 24 h (ADR 0041)."""

    __tablename__ = "export_files"

    kind: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(EXPORT_FORMAT)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(EXPORT_STATUS, server_default="pending")
    # Différé : lister les exports ne charge pas leurs 10 Mo de contenu.
    content: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True))
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Défaut serveur de la révision 0013 : 24 h après la demande.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now() + interval '24 hours'")
    )
