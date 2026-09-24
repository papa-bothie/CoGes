"""Routes HTTP du module Sales. Aucune requête SQL ici.

Une vente ne se supprime pas : il n'y a ni `DELETE /sales/{id}`, ni suppression
logique. Une vente qui n'aurait pas dû exister s'annule, avec un motif, et la trace
reste. L'absence de cette route est une information, pas un oubli.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.deps import TenantSession, client_ip, require_permission
from app.core.repository import MAX_PAGE_SIZE
from app.modules.sales import service
from app.modules.sales.schemas import (
    ReceiptRead,
    SaleCancel,
    SaleConfirm,
    SaleCreate,
    SaleDetail,
    SaleItemCreate,
    SaleItemRead,
    SaleItemUpdate,
    SalePage,
    SaleStatus,
    SaleUpdate,
)

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("", response_model=SaleDetail, status_code=status.HTTP_201_CREATED)
def create_sale(
    payload: SaleCreate,
    tenant: Annotated[TenantSession, Depends(require_permission("sales:create"))],
) -> SaleDetail:
    """Ouvre un brouillon. Aucun effet de bord tant qu'il n'est pas confirmé."""
    sale = service.create_sale(tenant.session, tenant.ctx, payload)
    return service.build_detail(tenant.session, tenant.ctx, sale)


@router.get("", response_model=SalePage)
def list_sales(
    tenant: Annotated[TenantSession, Depends(require_permission("sales:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    sale_status: Annotated[SaleStatus | None, Query(alias="status")] = None,
    customer_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    sale_no: Annotated[str | None, Query(alias="search")] = None,
) -> SalePage:
    """Ventes de la plus récente à la plus ancienne, filtrables.

    `search` cherche un **numéro exact** : un numéro se dicte et se retrouve
    entier, une recherche approximative n'y aiderait personne.
    """
    sales, total, with_returns = service.list_sales(
        tenant.session,
        tenant.ctx,
        page=page,
        page_size=page_size,
        status=sale_status,
        customer_id=customer_id,
        date_from=date_from,
        date_to=date_to,
        sale_no=sale_no,
    )
    return SalePage(
        items=[service.build_read(sale, has_returns=sale.id in with_returns) for sale in sales],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{sale_id}", response_model=SaleDetail)
def get_sale(
    sale_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("sales:read"))],
) -> SaleDetail:
    """Vente complète : en-tête, lignes, règlements et dette éventuelle."""
    sale = service.get_sale(tenant.session, tenant.ctx, sale_id)
    return service.build_detail(tenant.session, tenant.ctx, sale)


@router.get("/{sale_id}/receipt", response_model=ReceiptRead)
def get_receipt(
    sale_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("sales:read"))],
) -> ReceiptRead:
    """Reçu d'une vente, en JSON. La mise en page est au frontend (ADR 0022)."""
    return service.build_receipt(tenant.session, tenant.ctx, sale_id)


@router.patch("/{sale_id}", response_model=SaleDetail)
def update_sale(
    sale_id: UUID,
    payload: SaleUpdate,
    tenant: Annotated[TenantSession, Depends(require_permission("sales:update"))],
) -> SaleDetail:
    """Change le client ou la date d'un brouillon."""
    sale = service.update_sale(tenant.session, tenant.ctx, sale_id, payload)
    return service.build_detail(tenant.session, tenant.ctx, sale)


@router.post("/{sale_id}/items", response_model=SaleItemRead, status_code=status.HTTP_201_CREATED)
def add_item(
    sale_id: UUID,
    payload: SaleItemCreate,
    tenant: Annotated[TenantSession, Depends(require_permission("sales:update"))],
) -> SaleItemRead:
    """Ajoute une ligne à un brouillon, au prix et au taux du moment."""
    item = service.add_item(tenant.session, tenant.ctx, sale_id, payload)
    return SaleItemRead.model_validate(item)


@router.patch("/{sale_id}/items/{item_id}", response_model=SaleItemRead)
def update_item(
    sale_id: UUID,
    item_id: UUID,
    payload: SaleItemUpdate,
    tenant: Annotated[TenantSession, Depends(require_permission("sales:update"))],
) -> SaleItemRead:
    """Corrige la quantité ou la remise d'une ligne de brouillon."""
    item = service.update_item(tenant.session, tenant.ctx, sale_id, item_id, payload)
    return SaleItemRead.model_validate(item)


@router.delete("/{sale_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(
    sale_id: UUID,
    item_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("sales:update"))],
) -> Response:
    """Retire une ligne d'un brouillon."""
    service.remove_item(tenant.session, tenant.ctx, sale_id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{sale_id}/confirm", response_model=SaleDetail)
def confirm_sale(
    sale_id: UUID,
    payload: SaleConfirm,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("sales:confirm"))],
) -> SaleDetail:
    """Confirme la vente : stock, encaissement, dette, audit et événement.

    Une vente déjà confirmée est refusée en 409 `sale_not_draft` : la confirmation
    n'est pas idempotente, et un second appel doit être vu comme le conflit qu'il
    est — deux caissiers présentant deux règlements différents (ADR 0022).
    """
    sale = service.confirm_sale(
        tenant.session, tenant.ctx, sale_id, payload, ip_address=client_ip(request)
    )
    return service.build_detail(tenant.session, tenant.ctx, sale)


@router.post("/{sale_id}/cancel", response_model=SaleDetail)
def cancel_sale(
    sale_id: UUID,
    payload: SaleCancel,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("sales:cancel"))],
) -> SaleDetail:
    """Annule une vente confirmée : mouvements inverses, dette abandonnée, motif.

    Réservé au gérant : une annulation touche à la fois le stock, la finance et la
    dette (ADR 0007).
    """
    sale = service.cancel_sale(
        tenant.session, tenant.ctx, sale_id, payload, ip_address=client_ip(request)
    )
    return service.build_detail(tenant.session, tenant.ctx, sale)
