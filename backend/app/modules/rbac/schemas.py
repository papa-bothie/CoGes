"""Schémas du module RBAC."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    code: str
    resource: str
    action: str


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    name: str
    description: str | None
    is_system: bool


class RoleDetail(RoleRead):
    permissions: list[str]


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None


class RoleAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: UUID


class RolePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RoleRead]
    page: int
    page_size: int
    total: int


class AbilityRead(BaseModel):
    """Une ligne de la grille « Qui peut faire quoi » (ADR 0075)."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    permissions: list[str]
    #: Vraie pour les lignes qui ne se changent pas : l'accueil et les alertes (à tous),
    #: gérer les personnes et les réglages de l'entreprise (au gérant).
    locked: bool


class RoleAbilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: UUID
    name: str
    label: str
    #: Vraie pour le gérant : il garde tout, sa colonne ne se modifie pas.
    locked: bool
    #: Clés des lignes cochées : le rôle porte toutes leurs permissions.
    abilities: list[str]
    #: Lignes « en partie » : le rôle en porte certains droits, pas tous (ADR 0099).
    partial: list[str]


class AbilityGrid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abilities: list[AbilityRead]
    roles: list[RoleAbilities]


class AbilitiesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Clés des lignes cochées, sans doublon ; les autres sont décochées.
    abilities: list[str] = Field(max_length=20)
