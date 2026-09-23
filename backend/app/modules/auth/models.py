"""Modèles du module Auth."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.core.database import IdentifiedTenantBase


class AuthSession(IdentifiedTenantBase):
    """Refresh token rotatif (point P3).

    Seule l'**empreinte** est stockée. `family_id` regroupe toutes les rotations
    issues d'une même connexion : rejouer un jeton déjà consommé révoque la famille
    entière.
    """

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(Text)
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
