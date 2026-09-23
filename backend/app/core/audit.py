"""Audit critique — canal 1 (transactionnel).

Écrit **dans la même session et la même transaction** que l'opération métier. Il
n'appelle ni Redis, ni un worker : l'audit essentiel ne dépend d'aucune
infrastructure asynchrone (décision 05). Il est perdu si et seulement si
l'opération elle-même est annulée.

Opérations exigeant ce canal : données financières, suppressions logiques
importantes, changements de rôle ou de permission, paramètres sensibles, dettes,
paiements, annulations et retours de vente, ajustements manuels de stock.

Tout le reste — consultation, export, **connexion réussie**, notification — relève
du canal asynchrone (phase 08).
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext


class AuditAction(StrEnum):
    """Valeurs admises par le `CHECK` de `audit_logs.action` (§ 8.8)."""

    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    EXPORT = "export"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    REBUILD = "rebuild"


_INSERT_AUDIT = text(
    """
    INSERT INTO audit_logs
        (company_id, actor_user_id, action, entity_table, entity_id, diff, ip_address)
    VALUES (:company_id, :actor_user_id, :action, :entity_table, :entity_id,
            CAST(:diff AS jsonb), CAST(:ip_address AS inet))
    RETURNING id
    """
)


def audit_critical(
    session: Session,
    ctx: TenantContext,
    *,
    action: AuditAction,
    entity_table: str,
    entity_id: UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> int:
    """Écrit une ligne d'audit critique dans la transaction courante.

    `before` et `after` sont conservés tels quels : c'est l'état antérieur qui rend
    une enquête possible après coup.
    """
    diff: dict[str, Any] = {"before": before, "after": after}
    result = session.execute(
        _INSERT_AUDIT,
        {
            "company_id": ctx.company_id,
            "actor_user_id": ctx.user_id,
            "action": action.value,
            "entity_table": entity_table,
            "entity_id": entity_id,
            "diff": json.dumps(diff, ensure_ascii=False, default=str),
            "ip_address": ip_address,
        },
    )
    return int(result.scalar_one())
