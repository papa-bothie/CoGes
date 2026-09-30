"""Routes HTTP du module RBAC."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.deps import TenantSession, client_ip, require_permission
from app.modules.rbac import service
from app.modules.rbac.repository import PermissionCatalogue
from app.modules.rbac.schemas import (
    PermissionRead,
    RoleCreate,
    RoleDetail,
    RolePage,
    RoleRead,
    RoleUpdate,
)

router = APIRouter(tags=["rbac"])

MAX_PAGE_SIZE = 100


@router.get("/permissions", response_model=list[PermissionRead])
def list_permissions(
    tenant: Annotated[TenantSession, Depends(require_permission("roles:read"))],
) -> list[PermissionRead]:
    """Catalogue global des droits, en lecture seule."""
    catalogue = PermissionCatalogue(tenant.session).all()
    return [PermissionRead.model_validate(permission) for permission in catalogue]


@router.get("/roles", response_model=RolePage)
def list_roles(
    tenant: Annotated[TenantSession, Depends(require_permission("roles:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> RolePage:
    """Rôles de l'entreprise."""
    roles, total = service.list_roles(tenant.session, tenant.ctx, page=page, page_size=page_size)
    return RolePage(
        items=[RoleRead.model_validate(role) for role in roles],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/roles", response_model=RoleDetail, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("roles:create"))],
) -> RoleDetail:
    """Crée un rôle personnalisé. Audit critique."""
    role = service.create_role(tenant.session, tenant.ctx, payload, ip_address=client_ip(request))
    codes = service.role_permissions(tenant.session, tenant.ctx, role.id)
    return RoleDetail(**RoleRead.model_validate(role).model_dump(), permissions=codes)


@router.get("/roles/{role_id}", response_model=RoleDetail)
def read_role(
    role_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("roles:read"))],
) -> RoleDetail:
    """Rôle du tenant courant. Celui d'une autre entreprise renvoie 404."""
    role = service.get_role(tenant.session, tenant.ctx, role_id)
    codes = service.role_permissions(tenant.session, tenant.ctx, role_id)
    return RoleDetail(**RoleRead.model_validate(role).model_dump(), permissions=codes)


@router.patch("/roles/{role_id}", response_model=RoleDetail)
def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("roles:update"))],
) -> RoleDetail:
    """Modifie un rôle. Audit critique."""
    role = service.update_role(
        tenant.session, tenant.ctx, role_id, payload, ip_address=client_ip(request)
    )
    codes = service.role_permissions(tenant.session, tenant.ctx, role_id)
    return RoleDetail(**RoleRead.model_validate(role).model_dump(), permissions=codes)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: UUID,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("roles:delete"))],
) -> None:
    """Supprime un rôle sans porteur. Un rôle système est refusé."""
    service.delete_role(tenant.session, tenant.ctx, role_id, ip_address=client_ip(request))


# Attribution et retrait d'un rôle : routes servies par Users (ADR 0054), qui garde
# l'entreprise d'une situation sans gérant actif — RBAC ne lit pas `users`.
