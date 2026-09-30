"""Façade de services du module Audit. Lecture seule, sans effet de bord.

Les deux canaux d'audit (critique dans la transaction, secondaire par le worker)
écrivent la même table avec la même forme : le journal les lit ensemble.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.schemas import AuditLogRead
from app.modules.users import service as users_service


def list_logs(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    actor_user_id: UUID | None = None,
    action: str | None = None,
    entity_table: str | None = None,
    entity_id: UUID | None = None,
    period_from: datetime | None = None,
    period_to: datetime | None = None,
) -> tuple[list[AuditLogRead], int]:
    """Page du journal, la plus récente d'abord, auteurs nommés en une requête."""
    repository = AuditLogRepository(session, ctx)
    filters = {
        "actor_user_id": actor_user_id,
        "action": action,
        "entity_table": entity_table,
        "entity_id": entity_id,
        "period_from": period_from,
        "period_to": period_to,
    }
    rows = repository.page(page=page, page_size=page_size, **filters)
    actors = users_service.names_by_id(
        session, ctx, list({row.actor_user_id for row in rows if row.actor_user_id is not None})
    )
    items = [
        AuditLogRead(
            id=row.id,
            actor_user_id=row.actor_user_id,
            actor_name=actors.get(row.actor_user_id) if row.actor_user_id else None,
            action=row.action,
            entity_table=row.entity_table,
            entity_id=row.entity_id,
            diff=row.diff,
            ip_address=row.ip_address,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]
    return items, repository.count(**filters)
