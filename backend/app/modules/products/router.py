"""Routes HTTP du module Products. Aucune requête SQL ici."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.deps import TenantSession, client_ip, require_permission
from app.core.repository import MAX_PAGE_SIZE
from app.modules.products import service
from app.modules.products.schemas import (
    ProductCreate,
    ProductPage,
    ProductPriceCreate,
    ProductPricePage,
    ProductPriceRead,
    ProductRead,
    ProductUpdate,
)

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ProductPage)
def list_products(
    tenant: Annotated[TenantSession, Depends(require_permission("products:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    search: Annotated[str | None, Query(max_length=120)] = None,
    category_id: Annotated[UUID | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> ProductPage:
    """Liste paginée, avec le prix courant de chaque produit.

    Le **stock** n'y figure pas : `products` (bande B) ne peut pas dépendre
    d'`inventory` (bande C). La vue jointe sera un endpoint d'Inventory (ADR 0012).
    """
    rows, total = service.list_products(
        tenant.session,
        tenant.ctx,
        page=page,
        page_size=page_size,
        search=search,
        category_id=category_id,
        is_active=is_active,
    )
    return ProductPage(
        items=[ProductRead.build(product, price) for product, price in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("products:create"))],
) -> ProductRead:
    """Crée la fiche et son premier prix dans la même transaction."""
    product, price = service.create_product(
        tenant.session, tenant.ctx, payload, ip_address=client_ip(request)
    )
    return ProductRead.build(product, price)


@router.get("/{product_id}", response_model=ProductRead)
def read_product(
    product_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("products:read"))],
) -> ProductRead:
    """Produit du tenant courant. Celui d'une autre entreprise renvoie 404."""
    product, price = service.get_product_with_price(tenant.session, tenant.ctx, product_id)
    return ProductRead.build(product, price)


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    tenant: Annotated[TenantSession, Depends(require_permission("products:update"))],
) -> ProductRead:
    """Modifie la fiche. Le prix a son propre endpoint."""
    product, price = service.update_product(tenant.session, tenant.ctx, product_id, payload)
    return ProductRead.build(product, price)


@router.delete("/{product_id}", response_model=ProductRead)
def delete_product(
    product_id: UUID,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("products:delete"))],
) -> ProductRead:
    """Suppression **logique**, auditée : la ligne reste en base."""
    product, price = service.delete_product(
        tenant.session, tenant.ctx, product_id, ip_address=client_ip(request)
    )
    return ProductRead.build(product, price)


@router.get("/{product_id}/prices", response_model=ProductPricePage)
def list_prices(
    product_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("prices:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> ProductPricePage:
    """Historique des prix, du plus récent au plus ancien."""
    prices, total = service.list_prices(
        tenant.session, tenant.ctx, product_id, page=page, page_size=page_size
    )
    return ProductPricePage(
        items=[ProductPriceRead.model_validate(price) for price in prices],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/{product_id}/prices", response_model=ProductPriceRead, status_code=status.HTTP_201_CREATED
)
def change_price(
    product_id: UUID,
    payload: ProductPriceCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("prices:create"))],
) -> ProductPriceRead:
    """Ferme le prix courant et en ouvre un nouveau, au même instant, sous audit."""
    price = service.change_price(
        tenant.session, tenant.ctx, product_id, payload, ip_address=client_ip(request)
    )
    return ProductPriceRead.model_validate(price)
