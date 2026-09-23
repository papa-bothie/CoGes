"""Schémas du module Companies."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompanyRead(BaseModel):
    """Vue publique de l'entreprise courante."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    name: str
    slug: str
    currency: str
    timezone: str
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CompanyUpdate(BaseModel):
    """Paramètres modifiables. Chaque modification est auditée en transactionnel."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    settings: dict[str, Any] | None = None
