"""Modèles du module RBAC."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.core.database import Base, IdentifiedTenantBase, TenantBase


class Role(IdentifiedTenantBase):
    """Rôle RBAC, propre à une entreprise."""

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Permission(Base):
    """Catalogue **global** des droits : aucune donnée d'entreprise, pas de RLS.

    En lecture seule pour l'application : il est livré par migration (ADR 0004).
    """

    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(Text)
    resource: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)


class UserRole(TenantBase):
    """Rattachement utilisateur ↔ rôle, garanti intra-tenant par FK composite."""

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class RolePermission(TenantBase):
    """Rattachement rôle ↔ permission du catalogue global."""

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
