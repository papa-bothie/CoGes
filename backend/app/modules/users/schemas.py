"""Schémas du module Users."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRoleRead(BaseModel):
    """Rôle porté par un compte. `description` est le libellé affiché (ADR 0007)."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    name: str
    description: str | None
    is_system: bool


class UserRead(BaseModel):
    """Vue publique d'un utilisateur. Le hachage du mot de passe n'en fait jamais partie."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    email: str
    full_name: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    #: Rôles du compte (ADR 0053) : l'écran Utilisateurs les affiche sans N+1.
    roles: list[UserRoleRead] = Field(default_factory=list)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=128)
    role_ids: list[UUID] = Field(default_factory=list)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=12, max_length=128)


class UserPage(BaseModel):
    """Page de résultats. La pagination est obligatoire sur toutes les listes."""

    model_config = ConfigDict(extra="forbid")

    items: list[UserRead]
    page: int
    page_size: int
    total: int
