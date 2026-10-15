"""Façade de services du module Users.

Dépend de RBAC par sa **façade de services**, jamais par son repository ni ses
modèles (décision 01).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import BusinessRuleError, NotFoundError, ValidationFailedError
from app.core.passwords import readable_password
from app.core.security import hash_password, verify_password
from app.core.tenancy import TenantContext
from app.modules.rbac import service as rbac_service
from app.modules.rbac.matrix import MANAGER
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import (
    PasswordChange,
    UserCreate,
    UserRead,
    UserRoleRead,
    UserUpdate,
)


class LastManagerError(BusinessRuleError):
    """L'action laisserait l'entreprise sans gérant actif (ADR 0054).

    Plus personne ne pourrait alors gérer les comptes, les rôles ni les paramètres :
    seule la CLI rétablirait l'accès. Le refus est donc la règle.
    """

    code = "last_manager"
    default_message = (
        "Impossible : l'entreprise n'aurait plus aucun gérant actif. "
        "Nommez d'abord un autre gérant."
    )


class CurrentPasswordMismatchError(BusinessRuleError):
    """Le mot de passe actuel tapé n'est pas le bon : rien ne change."""

    code = "current_password_mismatch"
    default_message = "Le mot de passe actuel ne correspond pas."


class SamePasswordError(BusinessRuleError):
    """Le nouveau mot de passe est l'ancien : l'obligation de le changer resterait vaine."""

    code = "same_password"
    default_message = "Choisissez un mot de passe différent de l'actuel."


_SELF_DEACTIVATION = "Vous ne pouvez pas désactiver votre propre compte."


def _assert_a_manager_remains(session: Session, ctx: TenantContext, losing: UUID) -> None:
    """Refuse que `losing` cesse d'être gérant actif s'il est le dernier.

    Le verrou est pris **avant** de compter : deux retraits concurrents se succèdent, et
    le second compte les gérants actifs après le COMMIT du premier (ADR 0054).
    """
    UserRepository(session, ctx).lock_manager_guard()
    role_id = rbac_service.system_role_id(session, ctx, MANAGER)
    if role_id is None:
        return
    holders = rbac_service.holders_of_role(session, ctx, role_id)
    if losing not in holders:
        return
    others = [user_id for user_id in holders if user_id != losing]
    if not active_among(session, ctx, others):
        raise LastManagerError(details={"user_id": str(losing)})


def list_users(
    session: Session, ctx: TenantContext, *, page: int, page_size: int
) -> tuple[Sequence[User], int]:
    repository = UserRepository(session, ctx)
    return repository.page_live(page=page, page_size=page_size), repository.count_live()


def get_user(session: Session, ctx: TenantContext, user_id: UUID) -> User:
    """Utilisateur du tenant courant. Celui d'une autre entreprise donne 404."""
    user = UserRepository(session, ctx).get_live(user_id)
    if user is None:
        raise NotFoundError("Utilisateur introuvable.")
    return user


def create_user(
    session: Session,
    ctx: TenantContext,
    payload: UserCreate,
    *,
    ip_address: str | None = None,
) -> tuple[User, str | None]:
    """Crée un compte dans l'entreprise du contexte ; rend aussi son mot de passe
    provisoire s'il a été tiré par le serveur.

    L'e-mail est unique **par entreprise** : le même e-mail peut exister chez un
    autre tenant, ce sont deux comptes distincts (§ 2.2).
    """
    repository = UserRepository(session, ctx)
    if payload.email is not None and repository.get_by_email(str(payload.email)) is not None:
        raise ValidationFailedError(
            "Un compte utilise déjà cet e-mail dans cette entreprise.",
            details={"email": str(payload.email)},
        )
    if payload.phone is not None and repository.get_by_phone(payload.phone) is not None:
        raise ValidationFailedError(
            "Un compte utilise déjà ce numéro dans cette entreprise.",
            details={"phone": payload.phone},
        )

    # Sans mot de passe donné, un provisoire lisible, à changer à la première
    # connexion (ADR 0074). Un mot de passe choisi (CLI, seed, API) reste tel quel.
    temporary = payload.password is None
    password = readable_password() if temporary else str(payload.password)
    user = repository.add(
        User(
            company_id=ctx.company_id,
            email=str(payload.email) if payload.email is not None else None,
            phone=payload.phone,
            password_hash=hash_password(password),
            full_name=payload.full_name,
            is_active=True,
            must_change_password=temporary,
        )
    )
    session.flush()

    for role_id in payload.role_ids:
        rbac_service.assign_role(session, ctx, user.id, role_id, ip_address=ip_address)

    return user, (password if temporary else None)


def update_user(
    session: Session,
    ctx: TenantContext,
    user_id: UUID,
    payload: UserUpdate,
    *,
    ip_address: str | None = None,
) -> User:
    """Modifie le nom ou l'activation d'un compte."""
    user = get_user(session, ctx, user_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return user

    if changes.get("is_active") is False and user.is_active:
        if user.id == ctx.user_id:
            raise ValidationFailedError(_SELF_DEACTIVATION)
        _assert_a_manager_remains(session, ctx, user.id)

    before = {field: getattr(user, field) for field in changes}
    for field, value in changes.items():
        setattr(user, field, value)
    session.flush()

    # La désactivation d'un compte est un changement d'accès : audit critique.
    if "is_active" in changes:
        audit_critical(
            session,
            ctx,
            action=AuditAction.UPDATE,
            entity_table="users",
            entity_id=user.id,
            before=before,
            after={field: getattr(user, field) for field in changes},
            ip_address=ip_address,
        )
    return user


def deactivate_user(
    session: Session, ctx: TenantContext, user_id: UUID, *, ip_address: str | None = None
) -> User:
    """Suppression **logique** : `deleted_at` renseigné, la ligne reste en base."""
    user = get_user(session, ctx, user_id)
    if user.id == ctx.user_id:
        raise ValidationFailedError(_SELF_DEACTIVATION)
    _assert_a_manager_remains(session, ctx, user.id)

    before = {"is_active": user.is_active, "deleted_at": user.deleted_at}
    user.is_active = False
    user.deleted_at = datetime.now(UTC)
    session.flush()

    audit_critical(
        session,
        ctx,
        action=AuditAction.DELETE,
        entity_table="users",
        entity_id=user.id,
        before=before,
        after={"is_active": user.is_active, "deleted_at": user.deleted_at},
        ip_address=ip_address,
    )
    return user


def change_password(
    session: Session,
    ctx: TenantContext,
    user_id: UUID,
    payload: PasswordChange,
    *,
    ip_address: str | None = None,
) -> User:
    """Remplace le mot de passe d'un **autre** compte : il devra le changer à sa
    prochaine connexion, puisque quelqu'un d'autre le connaît (ADR 0074). Le hachage
    n'apparaît jamais dans l'audit."""
    user = get_user(session, ctx, user_id)
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = user.id != ctx.user_id
    session.flush()

    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="users",
        entity_id=user.id,
        before={"password_changed": False},
        after={"password_changed": True},
        ip_address=ip_address,
    )
    return user


def change_own_password(
    session: Session,
    ctx: TenantContext,
    *,
    current_password: str,
    new_password: str,
    ip_address: str | None = None,
) -> User:
    """Le titulaire remplace son mot de passe ; l'obligation de le changer tombe."""
    user = get_user(session, ctx, ctx.user_id)
    if not verify_password(current_password, user.password_hash):
        raise CurrentPasswordMismatchError()
    if current_password == new_password:
        raise SamePasswordError()
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    session.flush()
    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="users",
        entity_id=user.id,
        before={"password_changed": False},
        after={"password_changed": True},
        ip_address=ip_address,
    )
    return user


def record_login(session: Session, user: User) -> None:
    """Horodate la dernière connexion. L'audit de connexion est **asynchrone**."""
    user.last_login_at = datetime.now(UTC)
    session.flush()


def active_among(session: Session, ctx: TenantContext, user_ids: Sequence[UUID]) -> list[UUID]:
    """Filtre une liste d'identifiants pour ne garder que les comptes vivants et actifs.

    Façade lecture seule pour la bande E : une alerte ne part pas vers un compte
    désactivé, et RBAC — qui sait *qui détient un droit* — n'a pas le droit de lire
    `users` pour le vérifier lui-même (décision 01).
    """
    if not user_ids:
        return []
    return UserRepository(session, ctx).active_ids(user_ids)


def to_read(session: Session, ctx: TenantContext, users: Sequence[User]) -> list[UserRead]:
    """Vues publiques d'une page d'utilisateurs, avec leurs rôles (façade RBAC)."""
    roles = rbac_service.roles_by_user(session, ctx, [user.id for user in users])
    return [
        UserRead.model_validate(user).model_copy(
            update={"roles": [UserRoleRead.model_validate(r) for r in roles.get(user.id, [])]}
        )
        for user in users
    ]


def names_by_id(session: Session, ctx: TenantContext, user_ids: Sequence[UUID]) -> dict[UUID, str]:
    """Noms complets d'utilisateurs du tenant, y compris supprimés (journal d'activité)."""
    if not user_ids:
        return {}
    return UserRepository(session, ctx).names_by_id(user_ids)


def assign_role(
    session: Session,
    ctx: TenantContext,
    user_id: UUID,
    role_id: UUID,
    *,
    ip_address: str | None = None,
) -> list[UUID]:
    """Attribue un rôle à un compte vivant du tenant (404 sinon)."""
    get_user(session, ctx, user_id)
    return rbac_service.assign_role(session, ctx, user_id, role_id, ip_address=ip_address)


def revoke_role(
    session: Session,
    ctx: TenantContext,
    user_id: UUID,
    role_id: UUID,
    *,
    ip_address: str | None = None,
) -> list[UUID]:
    """Retire un rôle, sauf s'il s'agit du dernier gérant actif (ADR 0054)."""
    user = get_user(session, ctx, user_id)
    if user.is_active and role_id == rbac_service.system_role_id(session, ctx, MANAGER):
        _assert_a_manager_remains(session, ctx, user.id)
    return rbac_service.revoke_role(session, ctx, user_id, role_id, ip_address=ip_address)
