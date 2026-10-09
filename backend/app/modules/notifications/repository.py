"""Requêtes du module Notifications — filtrées par tenant, sans règle métier."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select

from app.core.repository import MAX_PAGE_SIZE, TenantRepository
from app.modules.notifications.models import Notification


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
