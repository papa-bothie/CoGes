"""Modèles du module Users."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.core.database import IdentifiedTenantBase


class User(IdentifiedTenantBase):
    """Compte d'accès. 1 compte = 1 entreprise (§ 2.2 : pas de table de membership)."""

    __tablename__ = "users"

    #: E-mail, téléphone (chiffres seuls) ou les deux (révision 0019, ADR 0074).
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean)
    #: Vrai tant qu'un mot de passe donné par quelqu'un d'autre n'est pas remplacé.
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    #: Échéance du mot de passe provisoire (ADR 0078) ; `None` : aucune (choisi, ou
    #: provisoire antérieur à la révision 0022).
    must_change_password_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Moment où l'accès a été coupé, `None` tant qu'il est ouvert (révision 0020).
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
