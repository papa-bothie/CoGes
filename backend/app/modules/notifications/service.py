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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.core import cache, queue, webpush
from app.core.config import get_settings
from app.core.errors import BusinessRuleError, NotFoundError, ValidationFailedError
from app.core.tenancy import TenantContext, on_commit

# Ré-export : les textes du téléphone, un constructeur par type (ADR 0120). Les autres
# modules et les workers les prennent ici, jamais dans `notifications.push`.
from app.modules.notifications import push as _push_module
from app.modules.notifications.models import Notification, PushSubscription
from app.modules.notifications.push import (
    BURST_THRESHOLD,
    BURST_WINDOW_SECONDS,
    PUSH_DELIVER,
    SELF_SILENT_TYPES,
    PushMessage,
    burst,
    message_of,
)
from app.modules.notifications.repository import (
    NotificationRepository,
    PushSubscriptionRepository,
)
from app.modules.notifications.schemas import (
    CRITICAL_TYPES,
    NotificationType,
    PushConfig,
    PushSubscriptionCreate,
)

# Ré-export : la façade expose la gravité d'un type d'alerte (ADR 0059).
from app.modules.notifications.schemas import severity_of as severity_of
from app.modules.rbac import service as rbac_service
from app.modules.users import service as users_service

#: Les textes du téléphone, un constructeur par type (ADR 0120), exposés par la façade.
push_texts = _push_module

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
    # Qui gère les personnes gère aussi l'abonnement : le gérant (ADR 0091).
    NotificationType.TRIAL_ENDING: "users:update",
    # Le gérant répond de qui lit les données de la boutique (ADR 0092).
    NotificationType.SUPPORT_ACCESS: "users:update",
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
    ) -> UUID | None:
        """Remet l'alerte à une personne, dans la transaction en cours.

        Rend l'identifiant de l'alerte écrite, que l'envoi sur le téléphone relira après
        le COMMIT (ADR 0120), ou `None` pour un canal qui n'écrit rien en base.
        """
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
    ) -> UUID | None:
        notification = NotificationRepository(session, ctx).add_for_user(
            user_id=user_id,
            notification_type=notification_type.value,
            title=title,
            body=body,
            data=data,
        )
        session.flush()
        return notification.id


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
    push: PushMessage,
    actor_user_id: UUID | None = None,
    channel: NotificationChannel | None = None,
    dedupe_hours: int | None = None,
) -> int:
    """Alerte les personnes habilitées, sans doublon dans la fenêtre. Renvoie le compte.

    Le dédoublonnage porte sur (type, entité, destinataire) et sur une fenêtre de
    quelques heures : un stock bas est une **situation**, pas un flux d'événements. Sans
    cette fenêtre, chaque vente d'un article sous son seuil rouvrirait la même alerte,
    et un fil illisible ne prévient plus de rien. `dedupe_hours` la raccourcit pour une
    alerte qui doit pouvoir revenir plus tôt (échecs de connexion : une par heure).

    `push` : ce que dit le téléphone, écrit par type dans `notifications.push`, sans
    montant (ADR 0120). Gardé dans `data["push"]`, envoyé par le worker **après** le
    COMMIT : une alerte annulée avec sa transaction ne sonne jamais. `actor_user_id` :
    la personne dont le geste a provoqué l'alerte, que son propre téléphone ne dérange
    pas pour certains types (`SELF_SILENT_TYPES`).
    """
    permission = RECIPIENT_PERMISSION[notification_type]
    holders = rbac_service.user_ids_with_permission(session, ctx, permission)
    recipients = users_service.active_among(session, ctx, holders)
    if not recipients:
        return 0

    payload = dict(data or {})
    if entity_id is not None:
        payload["entity_id"] = entity_id
    payload["push"] = push.as_data()
    if actor_user_id is not None:
        payload["actor_user_id"] = str(actor_user_id)

    repository = NotificationRepository(session, ctx)
    window = dedupe_hours if dedupe_hours is not None else get_settings().notification_dedupe_hours
    since = datetime.now(UTC) - timedelta(hours=window)
    sink = channel or InAppChannel()

    delivered = 0
    created: list[UUID] = []
    for user_id in recipients:
        duplicate = repository.recent_duplicate(
            user_id=user_id,
            notification_type=notification_type.value,
            entity_id=entity_id,
            since=since,
        )
        if duplicate is not None:
            continue
        notification_id = sink.deliver(
            session,
            ctx,
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            body=body,
            data=payload,
        )
        if notification_id is not None:
            created.append(notification_id)
        delivered += 1
    if created and get_settings().push_enabled:
        company_id = str(ctx.company_id)
        ids = [str(notification_id) for notification_id in created]

        def _enqueue() -> None:
            queue.enqueue(PUSH_DELIVER, company_id=company_id, ids=ids)

        on_commit(session, _enqueue)
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


# ---------------------------------------------- notifications sur le téléphone (ADR 0120)


class PushUnavailableError(BusinessRuleError):
    code = "push_unavailable"
    default_message = "Les notifications sur le téléphone ne sont pas disponibles."


class PushEndpointRefusedError(ValidationFailedError):
    code = "push_endpoint_refused"
    default_message = (
        "Cet abonnement ne vient pas d'un service de notifications de navigateur connu."
    )


#: Après autant d'échecs de suite, un appareil muet est arrêté (ni 404 ni 410 reçus).
MAX_CONSECUTIVE_FAILURES = 10


def push_config() -> PushConfig:
    """La clé publique VAPID, ou `null` : sans clés, aucun bouton (ADR 0120)."""
    settings = get_settings()
    return PushConfig(public_key=settings.vapid_public_key if settings.push_enabled else None)


def subscribe(
    session: Session, ctx: TenantContext, payload: PushSubscriptionCreate
) -> PushSubscription:
    """Abonne l'appareil de la personne du jeton, pour elle seule.

    La même adresse déjà abonnée est reprise : par la même personne (clés rafraîchies),
    ou par une autre de la boutique, qui la remplace (téléphone partagé). Au-delà du
    plafond d'appareils, le plus ancien s'arrête.
    """
    settings = get_settings()
    if not settings.push_enabled:
        raise PushUnavailableError()
    endpoint = payload.endpoint.strip()
    if not webpush.push_host_allowed(endpoint) or not webpush.subscription_keys_valid(
        payload.keys.p256dh, payload.keys.auth
    ):
        raise PushEndpointRefusedError()

    repository = PushSubscriptionRepository(session, ctx)
    label = (payload.device_label or "").strip() or None
    existing = repository.live_by_endpoint(endpoint)
    if existing is not None and existing.user_id == ctx.user_id:
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
        existing.device_label = label
        existing.failure_count = 0
        session.flush()
        return existing
    if existing is not None:
        _stop(existing, "replaced")
        session.flush()

    subscription = repository.add(
        PushSubscription(
            company_id=ctx.company_id,
            user_id=ctx.user_id,
            endpoint=endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            device_label=label,
            failure_count=0,
        )
    )
    session.flush()
    live = repository.live_for_user(ctx.user_id)
    for oldest in live[: max(0, len(live) - settings.push_max_devices)]:
        _stop(oldest, "replaced")
    session.flush()
    return subscription


def unsubscribe(
    session: Session, ctx: TenantContext, endpoint: str, *, reason: str = "unsubscribed"
) -> bool:
    """Arrête l'abonnement de cet appareil, s'il est à la personne du jeton."""
    subscription = PushSubscriptionRepository(session, ctx).live_by_endpoint(endpoint.strip())
    if subscription is None or subscription.user_id != ctx.user_id:
        return False
    _stop(subscription, reason)
    session.flush()
    return True


def my_subscriptions(session: Session, ctx: TenantContext) -> list[PushSubscription]:
    return list(PushSubscriptionRepository(session, ctx).live_for_user(ctx.user_id))


def _stop(subscription: PushSubscription, reason: str) -> None:
    subscription.disabled_at = datetime.now(UTC)
    subscription.disabled_reason = reason


@dataclass(frozen=True, slots=True)
class PushOutgoing:
    """Une notification à envoyer à une personne, sur chacun de ses appareils."""

    user_id: UUID
    message: PushMessage
    targets: list[tuple[UUID, webpush.PushTarget]]


def push_plan(
    session: Session, ctx: TenantContext, notification_ids: Sequence[UUID]
) -> list[PushOutgoing]:
    """Ce qui part, après le COMMIT des alertes (ADR 0120). Lecture seule.

    Une alerte relue ici a bien été validée : celle d'une transaction annulée n'existe
    pas. Pas de notification à qui a provoqué une annulation ou une correction ; au-delà
    de 3 alertes en une minute pour une personne, un seul message « N nouvelles alertes ».
    """
    notifications = NotificationRepository(session, ctx).by_ids(notification_ids)
    by_user: dict[UUID, list[Notification]] = {}
    for notification in notifications:
        if notification.user_id is None:
            continue
        actor = notification.data.get("actor_user_id")
        if notification.type in SELF_SILENT_TYPES and actor == str(notification.user_id):
            continue
        by_user.setdefault(notification.user_id, []).append(notification)
    if not by_user:
        return []

    subscriptions = PushSubscriptionRepository(session, ctx).live_for_users(list(by_user))
    targets: dict[UUID, list[tuple[UUID, webpush.PushTarget]]] = {}
    for subscription in subscriptions:
        targets.setdefault(subscription.user_id, []).append(
            (
                subscription.id,
                webpush.PushTarget(subscription.endpoint, subscription.p256dh, subscription.auth),
            )
        )

    since = datetime.now(UTC) - timedelta(seconds=BURST_WINDOW_SECONDS)
    repository = NotificationRepository(session, ctx)
    plan: list[PushOutgoing] = []
    for user_id, items in by_user.items():
        devices = targets.get(user_id)
        if not devices:
            continue
        recent = repository.created_since(user_id, since)
        if recent > BURST_THRESHOLD:
            plan.append(PushOutgoing(user_id, burst(recent), devices))
            continue
        plan.extend(PushOutgoing(user_id, message_of(item.data), devices) for item in items)
    return plan


def record_push_results(
    session: Session, ctx: TenantContext, results: Sequence[tuple[UUID, webpush.PushResult]]
) -> None:
    """Reçu : appareil à jour. 404 ou 410 : arrêté. Autre échec : compté, puis arrêté."""
    if not results:
        return
    subscriptions = {
        subscription.id: subscription
        for subscription in PushSubscriptionRepository(session, ctx).by_ids_for_update(
            [subscription_id for subscription_id, _ in results]
        )
    }
    now = datetime.now(UTC)
    for subscription_id, result in results:
        subscription = subscriptions.get(subscription_id)
        if subscription is None or subscription.disabled_at is not None:
            continue
        if result.delivered:
            subscription.last_success_at = now
            subscription.failure_count = 0
        elif result.gone:
            _stop(subscription, "gone")
        else:
            subscription.failure_count += 1
            if subscription.failure_count >= MAX_CONSECUTIVE_FAILURES:
                _stop(subscription, "failures")
    session.flush()


def push_allowed_this_hour(company_id: UUID, user_id: UUID) -> bool:
    """Plafond par personne et par heure (ADR 0120). Sans Redis, on laisse passer."""
    client = cache.get_client()
    if client is None:
        return True
    hour = datetime.now(UTC).strftime("%Y%m%d%H")
    name = cache.key(company_id, f"push:{user_id}:{hour}")
    try:
        sent = int(cast(int, client.incr(name)))
        if sent == 1:
            client.expire(name, 2 * 3600)
    except Exception:
        return True
    return sent <= get_settings().push_max_per_hour
