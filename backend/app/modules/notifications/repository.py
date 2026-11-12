"""Requêtes du module Notifications — filtrées par tenant, sans règle métier."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select, update

from app.core.repository import MAX_PAGE_SIZE, TenantRepository
from app.modules.notifications.models import Notification, PushSubscription


class NotificationRepository(TenantRepository[Notification]):
    """Le fil d'alertes d'un utilisateur, dans son entreprise."""

    model = Notification

    def _for_user(self, user_id: UUID) -> Select[tuple[Notification]]:
        """Alertes de cet utilisateur uniquement.

        Le fil est personnel : le `user_id` s'ajoute au filtre tenant, il ne le
        remplace pas. Les deux filtres sont indépendants — l'un protège de l'autre
        entreprise, l'autre du collègue.
        """
        return self._select().where(Notification.user_id == user_id)

    def page_for_user(
        self, user_id: UUID, *, page: int = 1, page_size: int = 20, unread_only: bool = False
    ) -> Sequence[Notification]:
        if page < 1:
            raise ValueError("page doit être >= 1")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size doit être entre 1 et {MAX_PAGE_SIZE}")
        stmt = self._for_user(user_id)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        stmt = (
            stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def count_for_user(
        self,
        user_id: UUID,
        *,
        unread_only: bool = False,
        types: Sequence[str] | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.company_id == self.ctx.company_id,
                Notification.user_id == user_id,
            )
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        if types is not None:
            stmt = stmt.where(Notification.type.in_(list(types)))
        return int(self.session.execute(stmt).scalar_one())

    def mark_all_read(self, user_id: UUID, at: dt.datetime) -> int:
        """Toutes les alertes non lues de cet utilisateur, lues à `at`."""
        stmt = (
            update(Notification)
            .where(
                Notification.company_id == self.ctx.company_id,
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=at)
        )
        return int(self.session.execute(stmt).rowcount or 0)  # type: ignore[attr-defined]

    def get_for_user(self, user_id: UUID, notification_id: UUID) -> Notification | None:
        stmt = self._for_user(user_id).where(Notification.id == notification_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def recent_duplicate(
        self,
        *,
        user_id: UUID,
        notification_type: str,
        entity_id: str | None,
        since: dt.datetime,
    ) -> Notification | None:
        """Alerte identique déjà envoyée à cette personne depuis `since`.

        La comparaison porte sur le type **et** sur l'entité concernée, lue dans
        `data`. Sans l'entité, deux produits différents en rupture le même jour se
        dédoublonneraient l'un l'autre — et le gérant n'entendrait parler que du
        premier.
        """
        stmt = self._for_user(user_id).where(
            Notification.type == notification_type,
            Notification.created_at >= since,
        )
        if entity_id is not None:
            stmt = stmt.where(Notification.data["entity_id"].astext == entity_id)
        stmt = stmt.order_by(Notification.created_at.desc()).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def by_ids(self, ids: Sequence[UUID]) -> Sequence[Notification]:
        if not ids:
            return []
        stmt = self._select().where(Notification.id.in_(list(set(ids))))
        return self.session.execute(stmt).scalars().all()

    def created_since(self, user_id: UUID, since: dt.datetime) -> int:
        """Alertes reçues par la personne depuis `since` (regroupement des rafales)."""
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.company_id == self.ctx.company_id,
                Notification.user_id == user_id,
                Notification.created_at >= since,
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def add_for_user(
        self,
        *,
        user_id: UUID,
        notification_type: str,
        title: str,
        body: str | None,
        data: dict[str, Any],
    ) -> Notification:
        return self.add(
            Notification(
                company_id=self.ctx.company_id,
                user_id=user_id,
                type=notification_type,
                title=title,
                body=body,
                data=data,
            )
        )


class PushSubscriptionRepository(TenantRepository[PushSubscription]):
    """Abonnements Web Push (ADR 0120). « Arrêter » remplace la suppression."""

    model = PushSubscription

    def live_by_endpoint(self, endpoint: str) -> PushSubscription | None:
        stmt = self._select().where(
            PushSubscription.endpoint == endpoint, PushSubscription.disabled_at.is_(None)
        )
        return self.session.execute(stmt.with_for_update()).scalar_one_or_none()

    def live_for_user(self, user_id: UUID) -> Sequence[PushSubscription]:
        """Appareils vivants d'une personne, du plus ancien au plus récent."""
        stmt = (
            self._select()
            .where(PushSubscription.user_id == user_id, PushSubscription.disabled_at.is_(None))
            .order_by(PushSubscription.created_at.asc(), PushSubscription.id.asc())
        )
        return self.session.execute(stmt).scalars().all()

    def live_for_users(self, user_ids: Sequence[UUID]) -> Sequence[PushSubscription]:
        if not user_ids:
            return []
        stmt = self._select().where(
            PushSubscription.user_id.in_(list(set(user_ids))),
            PushSubscription.disabled_at.is_(None),
        )
        return self.session.execute(stmt).scalars().all()

    def by_ids_for_update(self, ids: Sequence[UUID]) -> Sequence[PushSubscription]:
        if not ids:
            return []
        stmt = (
            self._select()
            .where(PushSubscription.id.in_(list(set(ids))))
            .order_by(PushSubscription.id)
            .with_for_update()
        )
        return self.session.execute(stmt).scalars().all()
