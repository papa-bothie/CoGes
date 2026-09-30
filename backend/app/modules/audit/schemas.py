"""Schémas du module Audit."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

#: Valeurs du `CHECK` de `audit_logs.action` (§ 8.8), identiques à `AuditAction`.
type AuditActionName = Literal[
    "insert", "update", "delete", "login", "export", "confirm", "cancel", "rebuild"
]


class AuditLogRead(BaseModel):
    """Une ligne du journal. `diff` est rendu tel qu'il a été écrit (avant / après)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    actor_user_id: UUID | None
    #: Nom de l'auteur, lu par la façade Users ; `null` pour un traitement système.
    actor_name: str | None
    action: AuditActionName
    entity_table: str
    entity_id: UUID | None
    diff: dict[str, Any] | None
    ip_address: str | None
    occurred_at: datetime


class AuditLogPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AuditLogRead]
    page: int
    page_size: int
    total: int
