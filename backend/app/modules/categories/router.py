"""Routes HTTP du module Categories. Aucune requête SQL ici.

Le router traduit HTTP ↔ schémas et vérifie la permission ; tout le reste est dans
le service. Une ressource appartenant à une autre entreprise sort en **404**, jamais
en 403 : le service lève `NotFoundError` avant toute autre considération.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.deps import TenantSession, client_ip, require_permission
from app.core.repository import MAX_PAGE_SIZE
from app.modules.categories import service
from app.modules.categories.schemas import (
    CategoryCreate,
    CategoryPage,
    CategoryRead,
    CategoryUpdate,
)

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=CategoryPage)
def list_categories(
    tenant: Annotated[TenantSession, Depends(require_permission("categories:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    search: Annotated[str | None, Query(max_length=120)] = None,
    parent_id: Annotated[UUID | None, Query()] = None,
) -> CategoryPage:
    """Liste paginée. `parent_id` restreint aux enfants directs d'une catégorie."""
    categories, total = service.list_categories(
        tenant.session,
        tenant.ctx,
        page=page,
        page_size=page_size,
        search=search,
        parent_id=parent_id,
    )
    return CategoryPage(
        items=[CategoryRead.model_validate(category) for category in categories],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    tenant: Annotated[TenantSession, Depends(require_permission("categories:create"))],
) -> CategoryRead:
    """Crée une catégorie, à la racine ou sous un parent de la même entreprise."""
    category = service.create_category(tenant.session, tenant.ctx, payload)
    return CategoryRead.model_validate(category)


@router.get("/{category_id}", response_model=CategoryRead)
def read_category(
    category_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("categories:read"))],
) -> CategoryRead:
    """Catégorie du tenant courant. Celle d'une autre entreprise renvoie 404."""
    category = service.get_category(tenant.session, tenant.ctx, category_id)
    return CategoryRead.model_validate(category)


@router.patch("/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: UUID,
    payload: CategoryUpdate,
    tenant: Annotated[TenantSession, Depends(require_permission("categories:update"))],
) -> CategoryRead:
    """Renomme une catégorie ou la déplace dans l'arbre."""
    category = service.update_category(tenant.session, tenant.ctx, category_id, payload)
    return CategoryRead.model_validate(category)


@router.delete("/{category_id}", response_model=CategoryRead)
def delete_category(
    category_id: UUID,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("categories:delete"))],
) -> CategoryRead:
    """Suppression **logique** : la ligne reste en base, `deleted_at` est renseigné."""
    category = service.delete_category(
        tenant.session, tenant.ctx, category_id, ip_address=client_ip(request)
    )
    return CategoryRead.model_validate(category)
