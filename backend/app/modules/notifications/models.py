"""Table `notifications` (§ 8.8). Colonnes, rien d'autre."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import NOW, IdentifiedTenantBase


class Notification(IdentifiedTenantBase):
    """Une alerte destinée à une personne."""

    __tablename__ = "notifications"

    #: `NULL` est autorisé par le schéma (alerte d'entreprise) mais le projet n'en
    #: écrit jamais : chaque alerte a son destinataire nommé (ADR 0032).
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    read_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=NOW, nullable=False)
