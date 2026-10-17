"""Façade de services du module Notifications.

Deux usages, aux droits opposés :

* **lecture** — un utilisateur consulte *son* fil, marque *ses* alertes comme lues ;
* **émission** — un worker crée des alertes après COMMIT, pour les personnes qui
  peuvent agir dessus.

Aucune alerte n'est jamais émise depuis une requête HTTP : `CLAUDE.md` interdit le
traitement long dans le chemin utilisateur, et surtout une alerte ratée ne doit pas
faire échouer la vente qui l'a provoquée.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.tenancy import TenantContext
from app.modules.notifications.models import Notification
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import CRITICAL_TYPES, NotificationType

# Ré-export : la façade expose la gravité d'un type d'alerte (ADR 0059).
from app.modules.notifications.schemas import severity_of as severity_of
from app.modules.rbac import service as rbac_service
from app.modules.users import service as users_service

#: Quel droit désigne le destinataire de chaque type d'alerte (ADR 0032).
#:
#: On alerte **celui qui peut agir**, pas un nom de rôle écrit en dur : le gérant seul
#: ajuste le stock (`inventory:update`, ADR 0007), le gérant et le comptable suivent
#: les dettes (`debts:update`), le gérant seul annule une vente (`sales:cancel`). Un
#: rôle personnalisé portant le droit reçoit donc l'alerte, sans rien changer ici.
RECIPIENT_PERMISSION: dict[NotificationType, str] = {
    NotificationType.STOCK_LOW: "inventory:update",
    NotificationType.STOCK_OUT: "inventory:update",
    NotificationType.DEBT_DUE: "debts:update",
    NotificationType.SALE_CANCELLED: "sales:cancel",
    # Un insight critique vise qui peut le lire : la permission de l'écran Insights.
    NotificationType.INSIGHT_CRITICAL: "insights:read",
    # Qui peut donner un nouveau mot de passe ou couper l'accès (ADR 0078).
    NotificationType.LOGIN_FAILURES: "users:update",
}


class NotificationChannel(Protocol):
    """Canal de remise d'une alerte.

    Une seule implémentation en V1 : l'écriture en base, lue par l'interface
    (`InAppChannel`). L'e-mail réserve sa place ici, sans fournisseur à choisir ni
    secret à gérer dans cette phase (ADR 0032) — le jour où il arrivera, il
    s'ajoutera, il ne remplacera pas.
    """

    def deliver(
        self,
        session: Session,
        ctx: TenantContext,
        *,
        user_id: UUID,
        notification_type: NotificationType,
        title: str,
        body: str | None,
        data: dict[str, Any],
    ) -> None:
        """Remet l'alerte à une personne, dans la transaction en cours."""
        ...


class InAppChannel:
    """Canal in-app : une ligne de `notifications` par destinataire."""

    def deliver(
        self,
        session: Session,
        ctx: TenantContext,
        *,
        user_id: UUID,
        notification_type: NotificationType,
        title: str,
        body: str | None,
        data: dict[str, Any],
    ) -> None:
        NotificationRepository(session, ctx).add_for_user(
            user_id=user_id,
            notification_type=notification_type.value,
            title=title,
            body=body,
            data=data,
        )


# ------------------------------------------------------------------------ émission


def notify(
    session: Session,
    ctx: TenantContext,
    *,
    notification_type: NotificationType,
    title: str,
    body: str | None = None,
    entity_id: str | None = None,
    data: dict[str, Any] | None = None,
    channel: NotificationChannel | None = None,
    dedupe_hours: int | None = None,
) -> int:
    """Alerte les personnes habilitées, sans doublon dans la fenêtre. Renvoie le compte.

    Le dédoublonnage porte sur (type, entité, destinataire) et sur une fenêtre de
    quelques heures : un stock bas est une **situation**, pas un flux d'événements. Sans
    cette fenêtre, chaque vente d'un article sous son seuil rouvrirait la même alerte,
    et un fil illisible ne prévient plus de rien. `dedupe_hours` la raccourcit pour une
    alerte qui doit pouvoir revenir plus tôt (échecs de connexion : une par heure).
    """
    permission = RECIPIENT_PERMISSION[notification_type]
    holders = rbac_service.user_ids_with_permission(session, ctx, permission)
    recipients = users_service.active_among(session, ctx, holders)
    if not recipients:
        return 0

    payload = dict(data or {})
    if entity_id is not None:
        payload["entity_id"] = entity_id

    repository = NotificationRepository(session, ctx)
    window = dedupe_hours if dedupe_hours is not None else get_settings().notification_dedupe_hours
    since = datetime.now(UTC) - timedelta(hours=window)
    sink = channel or InAppChannel()

    delivered = 0
    for user_id in recipients:
        duplicate = repository.recent_duplicate(
            user_id=user_id,
            notification_type=notification_type.value,
            entity_id=entity_id,
            since=since,
        )
        if duplicate is not None:
            continue
        sink.deliver(
            session,
            ctx,
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            body=body,
            data=payload,
        )
        delivered += 1
    return delivered


# ------------------------------------------------------------------------- lecture


def list_for_user(
    session: Session,
    ctx: TenantContext,
    *,
    page: int = 1,
    page_size: int = 20,
    unread_only: bool = False,
) -> tuple[list[Notification], int]:
    """Fil de l'utilisateur du contexte, le plus récent d'abord."""
    repository = NotificationRepository(session, ctx)
    items = repository.page_for_user(
        ctx.user_id, page=page, page_size=page_size, unread_only=unread_only
    )
    total = repository.count_for_user(ctx.user_id, unread_only=unread_only)
    return list(items), total


def unread_critical_count(session: Session, ctx: TenantContext) -> int:
    """Alertes graves non lues de l'utilisateur courant (badge de la cloche)."""
    return NotificationRepository(session, ctx).count_for_user(
        ctx.user_id, unread_only=True, types=[str(kind) for kind in CRITICAL_TYPES]
    )


def unread_count(session: Session, ctx: TenantContext) -> int:
    """Nombre d'alertes non lues de l'utilisateur du contexte."""
    return NotificationRepository(session, ctx).count_for_user(ctx.user_id, unread_only=True)


def set_read(
    session: Session, ctx: TenantContext, notification_id: UUID, *, read: bool
) -> Notification:
    """Marque une alerte comme lue, ou la rend à l'état non lu.

    L'alerte d'un collègue — comme celle d'une autre entreprise — renvoie **404** :
    apprendre qu'elle existe serait déjà une fuite.
    """
    repository = NotificationRepository(session, ctx)
    notification = repository.get_for_user(ctx.user_id, notification_id)
    if notification is None:
        raise NotFoundError("Cette alerte n'existe pas.")
    notification.read_at = datetime.now(UTC) if read else None
    session.flush()
    return notification


def mark_all_read(session: Session, ctx: TenantContext) -> int:
    """« Tout marquer comme lu » (écran 23) : seulement le fil de l'utilisateur."""
    return NotificationRepository(session, ctx).mark_all_read(ctx.user_id, datetime.now(UTC))
