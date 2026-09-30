"""Routes HTTP du module Inventory. Aucune requête SQL ici.

Le journal n'expose ni `PATCH` ni `DELETE` : il est append-only, et la seule
correction possible est `POST /movements/{id}/reverse`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status

from app.core.deps import TenantSession, client_ip, require_permission
from app.core.repository import MAX_PAGE_SIZE
from app.modules.inventory import service
from app.modules.inventory.schemas import (
    MovementCreate,
    MovementPage,
    MovementRead,
    MovementType,
    StockPage,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/stock", response_model=StockPage)
def list_stock(
    tenant: Annotated[TenantSession, Depends(require_permission("inventory:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    product_id: Annotated[list[UUID] | None, Query(max_length=MAX_PAGE_SIZE)] = None,
) -> StockPage:
    """Stock valorisé, article par article, ruptures en tête.

    C'est la vue « produits + stock » de l'ADR 0012 : elle appartient à Inventory,
    parce que Products n'a pas le droit de lire le stock. `product_id` se répète
    (au plus 100) pour lire le stock d'un lot d'articles ; un article sans aucun
    mouvement n'a pas de ligne.
    """
    items, total = service.get_stock(
        tenant.session, tenant.ctx, page=page, page_size=page_size, product_ids=product_id
    )
    return StockPage(items=items, page=page, page_size=page_size, total=total)


@router.get("/movements", response_model=MovementPage)
def list_movements(
    tenant: Annotated[TenantSession, Depends(require_permission("inventory:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    product_id: Annotated[UUID | None, Query()] = None,
    movement_type: Annotated[MovementType | None, Query(alias="type")] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> MovementPage:
    """Journal des mouvements, filtrable par produit, type et période."""
    rows, total = service.list_movements(
        tenant.session,
        tenant.ctx,
        page=page,
        page_size=page_size,
        product_id=product_id,
        movement_type=movement_type,
        date_from=date_from,
        date_to=date_to,
    )
    return MovementPage(
        items=[MovementRead.model_validate(movement) for movement in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/movements", response_model=MovementRead, status_code=status.HTTP_201_CREATED)
def record_movement(
    payload: MovementCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("inventory:create"))],
    idempotency_key: Annotated[UUID | None, Header(alias="Idempotency-Key")] = None,
) -> MovementRead:
    """Enregistre un mouvement manuel : stock, audit et événement en une transaction.

    `Idempotency-Key` est facultatif. Fourni, il rend le rejeu inoffensif : un
    second envoi de la même saisie est refusé par l'index `inv_ref_idempotence`.
    """
    movement = service.record_movement(
        tenant.session,
        tenant.ctx,
        payload,
        idempotency_key=idempotency_key,
        ip_address=client_ip(request),
    )
    return MovementRead.model_validate(movement)


@router.post(
    "/movements/{movement_id}/reverse",
    response_model=MovementRead,
    status_code=status.HTTP_201_CREATED,
)
def reverse_movement(
    movement_id: UUID,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("inventory:update"))],
) -> MovementRead:
    """Annule un mouvement par son inverse. Réservé au gérant (ADR 0007).

    Renvoie le mouvement **inverse** créé, pas celui d'origine : ce dernier n'a pas
    changé, et ne changera jamais.
    """
    reversal = service.reverse_movement(
        tenant.session, tenant.ctx, movement_id, ip_address=client_ip(request)
    )
    return MovementRead.model_validate(reversal)
