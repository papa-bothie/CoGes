"""Routes HTTP du module Audit. Aucune requête SQL ici."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.deps import TenantSession, require_permission
from app.core.repository import MAX_PAGE_SIZE
from app.modules.audit import service
from app.modules.audit.schemas import AuditActionName, AuditLogPage

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=AuditLogPage)
def list_audit_logs(
    tenant: Annotated[TenantSession, Depends(require_permission("audit:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    actor_user_id: Annotated[UUID | None, Query()] = None,
    action: Annotated[AuditActionName | None, Query()] = None,
    entity_table: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    entity_id: Annotated[UUID | None, Query()] = None,
    period_from: Annotated[datetime | None, Query(alias="from")] = None,
    period_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> AuditLogPage:
    """Journal d'activité : audit critique et secondaire, le plus récent d'abord.

    `audit:read` : gérant et comptable (ADR 0007, ADR 0053). Lecture seule — il
    n'existe aucune route pour corriger ou effacer une ligne du journal.
    """
    items, total = service.list_logs(
        tenant.session,
        tenant.ctx,
        page=page,
        page_size=page_size,
        actor_user_id=actor_user_id,
        action=action,
        entity_table=entity_table,
        entity_id=entity_id,
        period_from=period_from,
        period_to=period_to,
    )
    return AuditLogPage(items=items, page=page, page_size=page_size, total=total)
