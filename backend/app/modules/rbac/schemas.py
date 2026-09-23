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
