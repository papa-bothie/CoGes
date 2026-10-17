"""Routes HTTP du module Users."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.deps import TenantSession, client_ip, require_permission
from app.modules.rbac.schemas import RoleAssignment
from app.modules.users import service
from app.modules.users.models import User
from app.modules.users.schemas import (
    PasswordChange,
    UserCreate,
    UserCreated,
    UserPage,
    UserRead,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])


def _read(tenant: TenantSession, user: User) -> UserRead:
    return service.to_read(tenant.session, tenant.ctx, [user])[0]


MAX_PAGE_SIZE = 100


@router.get("", response_model=UserPage)
def list_users(
    tenant: Annotated[TenantSession, Depends(require_permission("users:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> UserPage:
    """Liste paginée des comptes de l'entreprise."""
    users, total = service.list_users(tenant.session, tenant.ctx, page=page, page_size=page_size)
    return UserPage(
        items=service.to_read(tenant.session, tenant.ctx, users),
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", response_model=UserCreated, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("users:create"))],
) -> UserCreated:
    """Crée un compte avec un e-mail, un téléphone ou les deux (ADR 0074).

    Sans mot de passe, le serveur en tire un provisoire lisible et le rend ici, **une
    seule fois** ; le compte devra le changer à sa première connexion.
    """
    user, temporary = service.create_user(
        tenant.session, tenant.ctx, payload, ip_address=client_ip(request)
    )
    return UserCreated(**_read(tenant, user).model_dump(), temporary_password=temporary)


@router.get("/{user_id}", response_model=UserRead)
def read_user(
    user_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("users:read"))],
) -> UserRead:
    """Compte du tenant courant. Celui d'une autre entreprise renvoie 404."""
    return _read(tenant, service.get_user(tenant.session, tenant.ctx, user_id))


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("users:update"))],
) -> UserRead:
    """Modifie le nom ou l'activation d'un compte."""
    user = service.update_user(
        tenant.session, tenant.ctx, user_id, payload, ip_address=client_ip(request)
    )
    return _read(tenant, user)


@router.delete("/{user_id}", response_model=UserRead)
def deactivate_user(
    user_id: UUID,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("users:delete"))],
) -> UserRead:
    """Désactivation **logique** : la ligne reste en base, `deleted_at` est renseigné."""
    user = service.deactivate_user(
        tenant.session, tenant.ctx, user_id, ip_address=client_ip(request)
    )
    return _read(tenant, user)


@router.post("/{user_id}/password", response_model=UserCreated)
def change_password(
    user_id: UUID,
    payload: PasswordChange,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("users:update"))],
) -> UserCreated:
    """Remplace le mot de passe d'un compte ; corps vide : provisoire tiré, rendu une fois."""
    user, temporary = service.change_password(
        tenant.session, tenant.ctx, user_id, payload, ip_address=client_ip(request)
    )
    return UserCreated(**_read(tenant, user).model_dump(), temporary_password=temporary)


@router.post("/{user_id}/roles", response_model=list[UUID], tags=["rbac"])
def assign_role(
    user_id: UUID,
    payload: RoleAssignment,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("roles:update"))],
) -> list[UUID]:
    """Attribue un rôle. Élévation de privilège : audit critique."""
    return service.assign_role(
        tenant.session, tenant.ctx, user_id, payload.role_id, ip_address=client_ip(request)
    )


@router.delete("/{user_id}/roles/{role_id}", response_model=list[UUID], tags=["rbac"])
def revoke_role(
    user_id: UUID,
    role_id: UUID,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("roles:update"))],
) -> list[UUID]:
    """Retire un rôle. Refusé (409 `last_manager`) s'il s'agit du dernier gérant actif."""
    return service.revoke_role(
        tenant.session, tenant.ctx, user_id, role_id, ip_address=client_ip(request)
    )
