"""Accès aux données du module RBAC."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from app.core.repository import TenantRepository
from app.core.tenancy import TenantContext
from app.modules.rbac.models import Permission, Role, RolePermission, UserRole


class RoleRepository(TenantRepository[Role]):
    """Rôles de l'entreprise du contexte."""

    model = Role

    def _ordered(self) -> Select[tuple[Role]]:
        return self._select().order_by(Role.name)

    def get_by_name(self, name: str) -> Role | None:
        return self.session.execute(self._select().where(Role.name == name)).scalar_one_or_none()

    def count(self) -> int:
        stmt = select(func.count()).select_from(Role).where(Role.company_id == self.ctx.company_id)
        return int(self.session.execute(stmt).scalar_one())

    def page(self, *, page: int = 1, page_size: int = 20) -> Sequence[Role]:
        stmt = self._ordered().limit(page_size).offset((page - 1) * page_size)
        return self.session.execute(stmt).scalars().all()

    def delete(self, role: Role) -> None:
        """Suppression physique, autorisée sur cette seule table (ADR 0007).

        La FK `user_roles -> roles` en `ON DELETE RESTRICT` empêche la base de
        supprimer un rôle encore porté par un utilisateur.
        """
        self.session.delete(role)


class PermissionCatalogue:
    """Catalogue global, hors RLS et en lecture seule."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def all(self) -> Sequence[Permission]:
        return self.session.execute(select(Permission).order_by(Permission.code)).scalars().all()

    def by_codes(self, codes: Sequence[str]) -> Sequence[Permission]:
        if not codes:
            return []
        stmt = select(Permission).where(Permission.code.in_(list(codes)))
        return self.session.execute(stmt).scalars().all()


class RolePermissionRepository:
    """Rattachements rôle ↔ permission, filtrés par tenant."""

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def codes_for_role(self, role_id: UUID) -> list[str]:
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(
                RolePermission.company_id == self.ctx.company_id,
                RolePermission.role_id == role_id,
            )
            .order_by(Permission.code)
        )
        return list(self.session.execute(stmt).scalars().all())

    def replace(self, role_id: UUID, permission_ids: Sequence[UUID]) -> None:
        """Remplace l'ensemble des permissions d'un rôle."""
        self.session.execute(
            delete(RolePermission).where(
                RolePermission.company_id == self.ctx.company_id,
                RolePermission.role_id == role_id,
            )
        )
        for permission_id in permission_ids:
            self.session.add(
                RolePermission(
                    company_id=self.ctx.company_id,
                    role_id=role_id,
                    permission_id=permission_id,
                )
            )


class UserRoleRepository:
    """Rattachements utilisateur ↔ rôle."""

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def role_ids_for_user(self, user_id: UUID) -> list[UUID]:
        stmt = select(UserRole.role_id).where(
            UserRole.company_id == self.ctx.company_id, UserRole.user_id == user_id
        )
        return list(self.session.execute(stmt).scalars().all())

    def grant(self, user_id: UUID, role_id: UUID) -> None:
        self.session.add(UserRole(company_id=self.ctx.company_id, user_id=user_id, role_id=role_id))

    def revoke(self, user_id: UUID, role_id: UUID) -> int:
        """Retire un rôle. Renvoie le nombre de rattachements effectivement supprimés."""
        statement = delete(UserRole).where(
            UserRole.company_id == self.ctx.company_id,
            UserRole.user_id == user_id,
            UserRole.role_id == role_id,
        )
        return int(self.session.execute(statement).rowcount or 0)  # type: ignore[attr-defined]

    def user_ids_with_permission(self, code: str) -> list[UUID]:
        """Utilisateurs de l'entreprise détenant ce droit, actifs ou non.

        Le filtre « actif » n'est **pas** posé ici : `users` appartient à un autre
        module, et RBAC n'a pas le droit d'en joindre les tables. C'est l'appelant qui
        compose les deux façades (décision 01).
        """
        stmt = (
            select(UserRole.user_id)
            .join(
                RolePermission,
                (RolePermission.role_id == UserRole.role_id)
                & (RolePermission.company_id == UserRole.company_id),
            )
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                UserRole.company_id == self.ctx.company_id,
                Permission.code == code,
            )
            .distinct()
            .order_by(UserRole.user_id)
        )
        return list(self.session.execute(stmt).scalars().all())

    def permission_codes_for_user(self, user_id: UUID) -> list[str]:
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(
                UserRole,
                (UserRole.role_id == RolePermission.role_id)
                & (UserRole.company_id == RolePermission.company_id),
            )
            .where(UserRole.company_id == self.ctx.company_id, UserRole.user_id == user_id)
            .distinct()
            .order_by(Permission.code)
        )
        return list(self.session.execute(stmt).scalars().all())
