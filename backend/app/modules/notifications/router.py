"""Routes HTTP du module Notifications. Aucune requête SQL ici.

Le fil est **personnel** : toutes les routes portent sur l'utilisateur du jeton, qui
n'a aucun moyen de désigner quelqu'un d'autre. Il n'existe donc pas de route
d'émission — une alerte naît d'un worker, jamais d'un appel client.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.core.deps import TenantSession, require_permission
from app.core.repository import MAX_PAGE_SIZE
from app.modules.notifications import service
from app.modules.notifications.schemas import (
    NotificationPage,
    NotificationRead,
    NotificationUpdate,
    PushConfig,
    PushSubscriptionCreate,
    PushSubscriptionList,
    PushSubscriptionRead,
    PushSubscriptionRemove,
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


@router.post("/read-all", response_model=UnreadCount)
def mark_all_read(
    tenant: Annotated[TenantSession, Depends(require_permission("notifications:update"))],
) -> UnreadCount:
    """« Tout marquer comme lu » : le fil de l'utilisateur courant, jamais celui d'un
    collègue. Rend le compteur, désormais à zéro."""
    service.mark_all_read(tenant.session, tenant.ctx)
    return UnreadCount(unread=0, critical=0)


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


# ------------------------------------------- notifications sur le téléphone (ADR 0120)
# Pour soi seulement : l'abonnement est rattaché à la personne du jeton, qui ne peut
# désigner personne d'autre. Le droit est celui de lire son fil.


@router.get("/push/config", response_model=PushConfig)
def push_config(
    _: Annotated[TenantSession, Depends(require_permission("notifications:read"))],
) -> PushConfig:
    """Clé publique VAPID, ou `null` : le bouton « Activer » n'apparaît pas sans elle."""
    return service.push_config()


@router.get("/push/subscriptions", response_model=PushSubscriptionList)
def my_push_subscriptions(
    tenant: Annotated[TenantSession, Depends(require_permission("notifications:read"))],
) -> PushSubscriptionList:
    """Appareils abonnés de la personne, sans leurs clés."""
    return PushSubscriptionList(
        items=[
            PushSubscriptionRead.model_validate(item)
            for item in service.my_subscriptions(tenant.session, tenant.ctx)
        ]
    )


@router.post("/push/subscriptions", response_model=PushSubscriptionRead, status_code=201)
def subscribe_push(
    payload: PushSubscriptionCreate,
    tenant: Annotated[TenantSession, Depends(require_permission("notifications:read"))],
) -> PushSubscriptionRead:
    """Abonne cet appareil. L'adresse doit venir d'un service de push connu."""
    return PushSubscriptionRead.model_validate(
        service.subscribe(tenant.session, tenant.ctx, payload)
    )


@router.post("/push/subscriptions/remove", status_code=204)
def unsubscribe_push(
    payload: PushSubscriptionRemove,
    tenant: Annotated[TenantSession, Depends(require_permission("notifications:read"))],
    logout: bool = False,
) -> Response:
    """Arrête l'abonnement de cet appareil (« Désactiver », ou la déconnexion).

    204 même si l'adresse est inconnue : rien n'est révélé, et la déconnexion n'échoue
    jamais pour un abonnement déjà arrêté.
    """
    service.unsubscribe(
        tenant.session,
        tenant.ctx,
        payload.endpoint,
        reason="logout" if logout else "unsubscribed",
    )
    return Response(status_code=204)
