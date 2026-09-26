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

from app.core import idempotency
from app.core.deps import TenantSession, client_ip, require_permission
from app.core.idempotency import IdempotencyKey
from app.core.repository import MAX_PAGE_SIZE
from app.modules.sales import service
from app.modules.sales.schemas import (
    ReceiptRead,
    RefundCreate,
    SaleCancel,
    SaleConfirm,
    SaleCreate,
    SaleDetail,
    SaleItemCreate,
    SaleItemRead,
    SaleItemUpdate,
    SalePage,
    SaleReturnCreate,
    SaleReturnDetail,
    SaleReturnList,
    SaleStatus,
    SaleUpdate,
)

router = APIRouter(prefix="/sales", tags=["sales"])

#: Un retour se crée **sur** une vente, mais se lit et se règle pour lui-même : il a
#: son numéro, son reste dû et sa vie propre. D'où deux préfixes, et non un seul.
returns_router = APIRouter(prefix="/sale-returns", tags=["sale_returns"])

#: Identifient l'écriture dans `idempotency_keys`. Ces deux endpoints déplacent de
#: l'argent — la confirmation encaisse et ouvre une dette, le remboursement
#: décaisse — et relèvent donc de la même règle que `POST /payments` : un double
#: clic ne doit pas produire deux écritures (décision 16, ADR 0027).
#:
#: Gabarits : l'identifiant de la ressource fait partie de l'endpoint enregistré.
#: Deux ventes au même corps partageraient sinon l'empreinte, et la même clé
#: présentée pour la seconde rejouerait la réponse de la première (ADR 0039).
CONFIRM_SALE_ENDPOINT = "POST /api/v1/sales/{sale_id}/confirm"
REFUND_RETURN_ENDPOINT = "POST /api/v1/sale-returns/{return_id}/refunds"


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
    sales, total, returned_totals = service.list_sales(
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
        items=[
            service.build_read(sale, returned_total=returned_totals.get(sale.id)) for sale in sales
        ],
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
    idempotency_key: IdempotencyKey,
) -> Response:
    """Confirme la vente : stock, encaissement, dette, audit et événement.

    Deux garde-fous qu'il ne faut pas confondre. La **clé d'idempotence** protège
    du réseau : la requête partie deux fois rejoue la même réponse. Le refus
    `sale_not_draft` (409) protège du métier : une seconde confirmation, avec une
    clé neuve, est un conflit réel — deux caissiers présentant deux règlements
    différents (ADR 0022). La première n'annule pas le second.
    """
    replay = idempotency.reserve(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        endpoint=CONFIRM_SALE_ENDPOINT.format(sale_id=sale_id),
        payload=payload,
    )
    if replay is not None:
        return idempotency.replay_response(replay)

    sale = service.confirm_sale(
        tenant.session, tenant.ctx, sale_id, payload, ip_address=client_ip(request)
    )
    return idempotency.completed(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        status_code=status.HTTP_200_OK,
        model=service.build_detail(tenant.session, tenant.ctx, sale),
    )


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


@router.post(
    "/{sale_id}/returns",
    response_model=SaleReturnDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_return(
    sale_id: UUID,
    payload: SaleReturnCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("sale_returns:create"))],
) -> SaleReturnDetail:
    """Enregistre un retour sur une vente confirmée : stock, montants, audit, événement.

    Le retour naît **non réglé**. Le remboursement, qui touche à l'argent, passe par
    `POST /sale-returns/{id}/refunds` et n'est pas ouvert au vendeur (ADR 0025).
    """
    sale_return = service.create_return(
        tenant.session, tenant.ctx, sale_id, payload, ip_address=client_ip(request)
    )
    return service.build_return_detail(tenant.session, tenant.ctx, sale_return)


@router.get("/{sale_id}/returns", response_model=SaleReturnList)
def list_sale_returns(
    sale_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("sale_returns:read"))],
) -> SaleReturnList:
    """Retours d'une vente, du plus récent au plus ancien."""
    return service.build_return_list(tenant.session, tenant.ctx, sale_id)


@returns_router.get("/{return_id}", response_model=SaleReturnDetail)
def get_return(
    return_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("sale_returns:read"))],
) -> SaleReturnDetail:
    """Retour complet : lignes rendues, lettrages et décaissements."""
    sale_return = service.get_return(tenant.session, tenant.ctx, return_id)
    return service.build_return_detail(tenant.session, tenant.ctx, sale_return)


@returns_router.post("/{return_id}/refunds", response_model=SaleReturnDetail)
def refund_return(
    return_id: UUID,
    payload: RefundCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("sale_returns:confirm"))],
    idempotency_key: IdempotencyKey,
) -> Response:
    """Règle tout ou partie d'un retour, en trésorerie ou par compensation.

    Réservé au gérant : `sale_returns:confirm` garde l'argent, comme
    `sales:cancel` garde l'annulation (ADR 0007 et 0025). Un montant qui dépasse le
    reste dû est refusé en 409, et les triggers le refuseraient de toute façon.

    Écriture financière, donc clé d'idempotence obligatoire : un remboursement
    envoyé deux fois rend la même réponse, et ne sort l'argent qu'une seule fois.
    """
    replay = idempotency.reserve(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        endpoint=REFUND_RETURN_ENDPOINT.format(return_id=return_id),
        payload=payload,
    )
    if replay is not None:
        return idempotency.replay_response(replay)

    sale_return = service.refund_return(
        tenant.session, tenant.ctx, return_id, payload, ip_address=client_ip(request)
    )
    return idempotency.completed(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        status_code=status.HTTP_200_OK,
        model=service.build_return_detail(tenant.session, tenant.ctx, sale_return),
    )
