"""Routes HTTP du module Users."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.deps import TenantSession, client_ip, require_permission
from app.modules.users import service
from app.modules.users.schemas import (
    PasswordChange,
    UserCreate,
    UserPage,
    UserRead,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])

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
        items=[UserRead.model_validate(user) for user in users],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("users:create"))],
) -> UserRead:
    """Crée un compte dans l'entreprise du contexte."""
    user = service.create_user(tenant.session, tenant.ctx, payload, ip_address=client_ip(request))
    return UserRead.model_validate(user)


@router.get("/{user_id}", response_model=UserRead)
def read_user(
    user_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("users:read"))],
) -> UserRead:
    """Compte du tenant courant. Celui d'une autre entreprise renvoie 404."""
    return UserRead.model_validate(service.get_user(tenant.session, tenant.ctx, user_id))


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
    return UserRead.model_validate(user)


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
    return UserRead.model_validate(user)


@router.post("/{user_id}/password", response_model=UserRead)
def change_password(
    user_id: UUID,
    payload: PasswordChange,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("users:update"))],
) -> UserRead:
    """Remplace le mot de passe d'un compte."""
    user = service.change_password(
        tenant.session, tenant.ctx, user_id, payload, ip_address=client_ip(request)
    )
    return UserRead.model_validate(user)
