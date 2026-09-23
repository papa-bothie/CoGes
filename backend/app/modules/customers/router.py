"""Routes HTTP du module Customers. Aucune requête SQL ici."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.deps import TenantSession, client_ip, require_permission
from app.core.repository import MAX_PAGE_SIZE
from app.modules.customers import service
from app.modules.customers.schemas import (
    CustomerCreate,
    CustomerPage,
    CustomerRead,
    CustomerUpdate,
)

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=CustomerPage)
def list_customers(
    tenant: Annotated[TenantSession, Depends(require_permission("customers:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    search: Annotated[str | None, Query(max_length=120)] = None,
) -> CustomerPage:
    """Liste paginée. `?search=` porte sur le nom et, à l'identique, sur le code."""
    customers, total = service.list_customers(
        tenant.session, tenant.ctx, page=page, page_size=page_size, search=search
    )
    return CustomerPage(
        items=[CustomerRead.model_validate(customer) for customer in customers],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    tenant: Annotated[TenantSession, Depends(require_permission("customers:create"))],
) -> CustomerRead:
    """Crée un client. Sans `code`, le serveur en attribue un (`CLI-0001`)."""
    customer = service.create_customer(tenant.session, tenant.ctx, payload)
    return CustomerRead.model_validate(customer)


@router.get("/{customer_id}", response_model=CustomerRead)
def read_customer(
    customer_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("customers:read"))],
) -> CustomerRead:
    """Client du tenant courant. Celui d'une autre entreprise renvoie 404."""
    customer = service.get_customer(tenant.session, tenant.ctx, customer_id)
    return CustomerRead.model_validate(customer)


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    tenant: Annotated[TenantSession, Depends(require_permission("customers:update"))],
) -> CustomerRead:
    """Modifie la fiche client."""
    customer = service.update_customer(tenant.session, tenant.ctx, customer_id, payload)
    return CustomerRead.model_validate(customer)


@router.delete("/{customer_id}", response_model=CustomerRead)
def delete_customer(
    customer_id: UUID,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("customers:delete"))],
) -> CustomerRead:
    """Suppression **logique**, auditée : la ligne reste en base."""
    customer = service.delete_customer(
        tenant.session, tenant.ctx, customer_id, ip_address=client_ip(request)
    )
    return CustomerRead.model_validate(customer)
