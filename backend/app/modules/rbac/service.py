"""Façade de services du module RBAC.

Tout changement de rôle ou de permission est une **élévation de privilège
potentielle** : il passe par un audit critique, dans la transaction (décision 05).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.tenancy import TenantContext
from app.modules.rbac.matrix import SYSTEM_ROLE_LABELS, SYSTEM_ROLES
from app.modules.rbac.models import Role
from app.modules.rbac.repository import (
    PermissionCatalogue,
    RolePermissionRepository,
    RoleRepository,
    UserRoleRepository,
)
from app.modules.rbac.schemas import RoleCreate, RoleUpdate


def permission_codes_for_user(session: Session, ctx: TenantContext, user_id: UUID) -> list[str]:
    """Permissions effectives d'un utilisateur, par ses rôles."""
    return UserRoleRepository(session, ctx).permission_codes_for_user(user_id)


def roles_for_user(session: Session, ctx: TenantContext, user_id: UUID) -> Sequence[Role]:
    """Rôles d'un utilisateur du tenant courant."""
    return RoleRepository(session, ctx).for_user(user_id)


def roles_by_user(
    session: Session, ctx: TenantContext, user_ids: Sequence[UUID]
) -> dict[UUID, list[Role]]:
    """Rôles d'une page d'utilisateurs, groupés par utilisateur (une seule requête)."""
    grouped: dict[UUID, list[Role]] = {user_id: [] for user_id in user_ids}
    for user_id, role in RoleRepository(session, ctx).for_users(user_ids):
        grouped.setdefault(user_id, []).append(role)
    return grouped


def list_roles(
    session: Session, ctx: TenantContext, *, page: int, page_size: int
) -> tuple[Sequence[Role], int]:
    repository = RoleRepository(session, ctx)
    return repository.page(page=page, page_size=page_size), repository.count()


def get_role(session: Session, ctx: TenantContext, role_id: UUID) -> Role:
    """Rôle du tenant courant. Celui d'une autre entreprise est introuvable : 404."""
    role = RoleRepository(session, ctx).get(role_id)
    if role is None:
        raise NotFoundError("Rôle introuvable.")
    return role


def role_permissions(session: Session, ctx: TenantContext, role_id: UUID) -> list[str]:
    return RolePermissionRepository(session, ctx).codes_for_role(role_id)


def _resolve_permission_ids(session: Session, codes: Sequence[str]) -> list[UUID]:
    """Traduit des codes en identifiants, en refusant tout code inconnu."""
    found = PermissionCatalogue(session).by_codes(codes)
    known = {permission.code: permission.id for permission in found}
    unknown = sorted(set(codes) - known.keys())
    if unknown:
        raise ValidationFailedError(
            "Permissions inconnues.", details={"unknown_permissions": unknown}
        )
    return [known[code] for code in codes]


def create_role(
    session: Session,
    ctx: TenantContext,
    payload: RoleCreate,
    *,
    ip_address: str | None = None,
) -> Role:
    """Crée un rôle personnalisé et lui attache ses permissions."""
    repository = RoleRepository(session, ctx)
    if repository.get_by_name(payload.name) is not None:
        raise ValidationFailedError("Un rôle porte déjà ce nom.", details={"name": payload.name})

    permission_ids = _resolve_permission_ids(session, payload.permissions)
    role = repository.add(
        Role(
            company_id=ctx.company_id,
            name=payload.name,
            description=payload.description,
            is_system=False,
        )
    )
    session.flush()
    RolePermissionRepository(session, ctx).replace(role.id, permission_ids)

    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT,
        entity_table="roles",
        entity_id=role.id,
        before=None,
        after={"name": role.name, "permissions": sorted(payload.permissions)},
        ip_address=ip_address,
    )
    return role


def update_role(
    session: Session,
    ctx: TenantContext,
    role_id: UUID,
    payload: RoleUpdate,
    *,
    ip_address: str | None = None,
) -> Role:
    """Modifie la description ou la matrice d'un rôle."""
    role = get_role(session, ctx, role_id)
    link_repository = RolePermissionRepository(session, ctx)
    before = {
        "description": role.description,
        "permissions": link_repository.codes_for_role(role_id),
    }

    if payload.description is not None:
        role.description = payload.description
    if payload.permissions is not None:
        if role.is_system:
            raise ValidationFailedError("Les permissions d'un rôle système ne se modifient pas.")
        link_repository.replace(role_id, _resolve_permission_ids(session, payload.permissions))
    session.flush()

    after = {
        "description": role.description,
        "permissions": link_repository.codes_for_role(role_id),
    }
    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="roles",
        entity_id=role.id,
        before=before,
        after=after,
        ip_address=ip_address,
    )
    return role


def delete_role(
    session: Session, ctx: TenantContext, role_id: UUID, *, ip_address: str | None = None
) -> None:
    """Supprime un rôle sans porteur. Un rôle système n'est jamais supprimable."""
    role = get_role(session, ctx, role_id)
    if role.is_system:
        raise ValidationFailedError("Un rôle système ne peut pas être supprimé.")

    link_repository = RolePermissionRepository(session, ctx)
    before = {"name": role.name, "permissions": link_repository.codes_for_role(role_id)}
    link_repository.replace(role_id, [])

    audit_critical(
        session,
        ctx,
        action=AuditAction.DELETE,
        entity_table="roles",
        entity_id=role.id,
        before=before,
        after=None,
        ip_address=ip_address,
    )
    # Après l'audit : si la FK ON DELETE RESTRICT refuse, toute la transaction tombe.
    RoleRepository(session, ctx).delete(role)
    session.flush()


def assign_role(
    session: Session,
    ctx: TenantContext,
    user_id: UUID,
    role_id: UUID,
    *,
    ip_address: str | None = None,
) -> list[UUID]:
    """Attribue un rôle à un utilisateur du même tenant."""
    get_role(session, ctx, role_id)  # 404 si le rôle appartient à une autre entreprise
    repository = UserRoleRepository(session, ctx)
    before = repository.role_ids_for_user(user_id)
    if role_id in before:
        return before

    repository.grant(user_id, role_id)
    session.flush()
    after = repository.role_ids_for_user(user_id)

    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="user_roles",
        entity_id=user_id,
        before={"role_ids": before},
        after={"role_ids": after},
        ip_address=ip_address,
    )
    return after


def revoke_role(
    session: Session,
    ctx: TenantContext,
    user_id: UUID,
    role_id: UUID,
    *,
    ip_address: str | None = None,
) -> list[UUID]:
    """Retire un rôle. La trace reste dans `audit_logs` (ADR 0007)."""
    repository = UserRoleRepository(session, ctx)
    before = repository.role_ids_for_user(user_id)
    if repository.revoke(user_id, role_id) == 0:
        raise NotFoundError("Ce rôle n'est pas attribué à cet utilisateur.")
    session.flush()
    after = repository.role_ids_for_user(user_id)

    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="user_roles",
        entity_id=user_id,
        before={"role_ids": before},
        after={"role_ids": after},
        ip_address=ip_address,
    )
    return after


def create_system_roles(session: Session, ctx: TenantContext) -> dict[str, Role]:
    """Crée les trois rôles système de l'entreprise (ADR 0007).

    Appelée à la création d'une entreprise. Le gérant reçoit **tout** le catalogue.
    """
    catalogue = PermissionCatalogue(session)
    every_code = [permission.code for permission in catalogue.all()]
    role_repository = RoleRepository(session, ctx)
    link_repository = RolePermissionRepository(session, ctx)

    created: dict[str, Role] = {}
    for name, codes in SYSTEM_ROLES.items():
        role = role_repository.add(
            Role(
                company_id=ctx.company_id,
                name=name,
                description=SYSTEM_ROLE_LABELS[name],
                is_system=True,
            )
        )
        session.flush()
        wanted = every_code if codes is None else sorted(codes)
        link_repository.replace(role.id, _resolve_permission_ids(session, wanted))
        created[name] = role

    session.flush()
    return created


def user_ids_with_permission(session: Session, ctx: TenantContext, code: str) -> list[UUID]:
    """Utilisateurs détenant ce droit — sans distinguer actifs et désactivés.

    Façade lecture seule pour la bande E (ADR 0032). Alerter par **droit** plutôt que
    par nom de rôle survit aux rôles personnalisés : c'est la même matrice qui décide
    qui peut annuler une vente et qui apprend qu'une vente a été annulée.

    Le tri entre comptes actifs et désactivés appartient à Users : l'appelant compose
    les deux façades, RBAC ne joint pas la table d'un autre module.
    """
    return UserRoleRepository(session, ctx).user_ids_with_permission(code)
