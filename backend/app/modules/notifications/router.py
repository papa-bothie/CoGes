"""Routes HTTP du module Notifications. Aucune requête SQL ici.

Le fil est **personnel** : toutes les routes portent sur l'utilisateur du jeton, qui
n'a aucun moyen de désigner quelqu'un d'autre. Il n'existe donc pas de route
d'émission — une alerte naît d'un worker, jamais d'un appel client.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.deps import TenantSession, require_permission
from app.core.repository import MAX_PAGE_SIZE
from app.modules.notifications import service
from app.modules.notifications.schemas import (
    NotificationPage,
    NotificationRead,
    NotificationUpdate,
    UnreadCount,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
def list_notifications(
    tenant: Annotated[TenantSession, Depends(require_permission("notifications:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    unread_only: Annotated[bool, Query(alias="unread")] = False,
) -> NotificationPage:
    """Fil paginé de l'utilisateur courant, le plus récent d'abord."""
    items, total = service.list_for_user(
        tenant.session, tenant.ctx, page=page, page_size=page_size, unread_only=unread_only
    )
    return NotificationPage(
        items=[NotificationRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/unread-count", response_model=UnreadCount)
def count_unread(
    tenant: Annotated[TenantSession, Depends(require_permission("notifications:read"))],
) -> UnreadCount:
    """Compteur de non-lus, pour la pastille de l'interface."""
    return UnreadCount(
        unread=service.unread_count(tenant.session, tenant.ctx),
        critical=service.unread_critical_count(tenant.session, tenant.ctx),
    )


@router.patch("/{notification_id}", response_model=NotificationRead)
def update_notification(
    notification_id: UUID,
    payload: NotificationUpdate,
    tenant: Annotated[TenantSession, Depends(require_permission("notifications:update"))],
) -> NotificationRead:
    """Marque l'alerte comme lue, ou la rend à l'état non lu.

    Aucun audit critique : une alerte lue n'est ni une donnée financière, ni une
    suppression, ni un changement de droit. Elle est jetable par construction (§ 6).
    """
    notification = service.set_read(tenant.session, tenant.ctx, notification_id, read=payload.read)
    return NotificationRead.model_validate(notification)
