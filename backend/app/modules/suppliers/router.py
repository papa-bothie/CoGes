"""Routes HTTP du module Suppliers. Aucune requête SQL ici."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.deps import TenantSession, client_ip, require_permission
from app.core.repository import MAX_PAGE_SIZE
from app.modules.suppliers import service
from app.modules.suppliers.schemas import (
    SupplierCreate,
    SupplierPage,
    SupplierRead,
    SupplierUpdate,
)

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=SupplierPage)
def list_suppliers(
    tenant: Annotated[TenantSession, Depends(require_permission("suppliers:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    search: Annotated[str | None, Query(max_length=120)] = None,
) -> SupplierPage:
    """Liste paginée. `?search=` porte sur le nom et, à l'identique, sur le code."""
    suppliers, total = service.list_suppliers(
        tenant.session, tenant.ctx, page=page, page_size=page_size, search=search
    )
    return SupplierPage(
        items=[SupplierRead.model_validate(supplier) for supplier in suppliers],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierCreate,
    tenant: Annotated[TenantSession, Depends(require_permission("suppliers:create"))],
) -> SupplierRead:
    """Crée un fournisseur. Sans `code`, le serveur en attribue un (`FRN-0001`)."""
    supplier = service.create_supplier(tenant.session, tenant.ctx, payload)
    return SupplierRead.model_validate(supplier)


@router.get("/{supplier_id}", response_model=SupplierRead)
def read_supplier(
    supplier_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("suppliers:read"))],
) -> SupplierRead:
    """Fournisseur du tenant courant. Celui d'une autre entreprise renvoie 404."""
    supplier = service.get_supplier(tenant.session, tenant.ctx, supplier_id)
    return SupplierRead.model_validate(supplier)


@router.patch("/{supplier_id}", response_model=SupplierRead)
def update_supplier(
    supplier_id: UUID,
    payload: SupplierUpdate,
    tenant: Annotated[TenantSession, Depends(require_permission("suppliers:update"))],
) -> SupplierRead:
    """Modifie la fiche fournisseur."""
    supplier = service.update_supplier(tenant.session, tenant.ctx, supplier_id, payload)
    return SupplierRead.model_validate(supplier)


@router.delete("/{supplier_id}", response_model=SupplierRead)
def delete_supplier(
    supplier_id: UUID,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("suppliers:delete"))],
) -> SupplierRead:
    """Suppression **logique**, auditée : la ligne reste en base."""
    supplier = service.delete_supplier(
        tenant.session, tenant.ctx, supplier_id, ip_address=client_ip(request)
    )
    return SupplierRead.model_validate(supplier)
