"""Routes HTTP du module Inventory. Aucune requête SQL ici.

Le journal n'expose ni `PATCH` ni `DELETE` : il est append-only, et la seule
correction possible est `POST /movements/{id}/reverse`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.core import idempotency
from app.core.deps import TenantSession, client_ip, require_permission
from app.core.idempotency import IdempotencyKey
from app.core.repository import MAX_PAGE_SIZE
from app.modules.inventory import service
from app.modules.inventory.schemas import (
    DeliveryCreate,
    DeliveryRead,
    MovementCreate,
    MovementPage,
    MovementRead,
    MovementType,
    NewProductCreate,
    NewProductRead,
    StockPage,
    StockStatus,
    StockSummary,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/stock", response_model=StockPage)
def list_stock(
    tenant: Annotated[TenantSession, Depends(require_permission("inventory:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    product_id: Annotated[list[UUID] | None, Query(max_length=MAX_PAGE_SIZE)] = None,
    stock_status: Annotated[StockStatus | None, Query(alias="status")] = None,
    category_id: Annotated[UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
) -> StockPage:
    """Stock valorisé, article par article, ruptures en tête.

    C'est la vue « produits + stock » de l'ADR 0012 : elle appartient à Inventory,
    parce que Products n'a pas le droit de lire le stock. `product_id` se répète
    (au plus 100) pour lire le stock d'un lot d'articles ; un article sans aucun
    mouvement n'a pas de ligne. `status`, `category_id` et `search` filtrent la liste de
    l'écran Stock (ADR 0071) ; chaque ligne porte son prix de vente et son niveau.
    """
    items, total = service.get_stock(
        tenant.session,
        tenant.ctx,
        page=page,
        page_size=page_size,
        product_ids=product_id,
        status=stock_status,
        category_id=category_id,
        search=search,
    )
    return StockPage(items=items, page=page, page_size=page_size, total=total)


@router.get("/stock/summary", response_model=StockSummary)
def stock_summary(
    tenant: Annotated[TenantSession, Depends(require_permission("inventory:read"))],
) -> StockSummary:
    """Nombre d'articles, valeur du stock au prix d'achat, bientôt épuisés et épuisés."""
    return service.stock_summary(tenant.session, tenant.ctx)


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


@router.post("/products", response_model=NewProductRead, status_code=status.HTTP_201_CREATED)
def create_product_with_stock(
    payload: NewProductCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("products:create"))],
    _stock: Annotated[TenantSession, Depends(require_permission("inventory:create"))],
) -> NewProductRead:
    """Crée un article et son stock d'ouverture dans la même transaction (ADR 0066).

    Sans référence ni code-barres, le serveur attribue `ART-0001` et un EAN-13 interne.
    Une quantité positive exige le prix d'achat, qui valorise le mouvement `initial`.
    """
    return service.create_product_with_stock(
        tenant.session, tenant.ctx, payload, ip_address=client_ip(request)
    )


#: Identifie l'écriture dans `idempotency_keys` : une livraison fait entrer du stock et
#: peut décaisser, rejouée après une coupure elle doublerait tout (ADR 0027, ADR 0071).
DELIVERY_ENDPOINT = "POST /api/v1/inventory/deliveries"


@router.post("/deliveries", response_model=DeliveryRead, status_code=status.HTTP_201_CREATED)
def receive_delivery(
    payload: DeliveryCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("inventory:create"))],
    _debts: Annotated[TenantSession, Depends(require_permission("debts:create"))],
    idempotency_key: IdempotencyKey,
) -> Response:
    """Reçoit une livraison : stock, dette fournisseur et paiement, tout ou rien (ADR 0071).

    « Tout maintenant » paie le total, « Une partie » le montant donné, « Plus tard »
    rien : le reste devient une dette envers le fournisseur, payable avant `due_date`.
    """
    replay = idempotency.reserve(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        endpoint=DELIVERY_ENDPOINT,
        payload=payload,
    )
    if replay is not None:
        return idempotency.replay_response(replay)
    delivery = service.receive_delivery(
        tenant.session, tenant.ctx, payload, ip_address=client_ip(request)
    )
    return idempotency.completed(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        status_code=status.HTTP_201_CREATED,
        model=delivery,
    )


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
