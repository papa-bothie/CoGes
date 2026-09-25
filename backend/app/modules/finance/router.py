"""Routes HTTP du module Finance. Aucune requête SQL ici.

Une seule route en phase 06, et elle répond à une question précise du § 5.4 : « quel
retour a provoqué cette sortie de trésorerie ». L'autre sens — d'un retour vers ses
remboursements — est rendu par Sales, qui possède les retours.

Pourquoi ici plutôt que dans Sales : la ressource interrogée est un **paiement**, et
les paiements appartiennent à Finance. La réponse ne porte donc que des lettrages,
sans numéro de retour : Finance est sous Sales dans l'ordre des dépendances et ne
l'importe jamais. Le frontend qui veut un `return_no` suit le `sale_return_id`.

La phase 07 y ajoute les écritures autonomes — encaisser, décaisser, affecter à
une ou plusieurs dettes — et la vie des dettes elles-mêmes. Toute écriture exige
un en-tête `Idempotency-Key` : un double clic au comptoir ne doit pas encaisser
deux fois.
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
from app.modules.finance import service
from app.modules.finance.schemas import (
    CashDirection,
    DebtCreate,
    DebtDetail,
    DebtPage,
    DebtStatus,
    DebtWriteOff,
    PartyType,
    PaymentCancel,
    PaymentCreate,
    PaymentDetail,
    PaymentPage,
    RefundLinkRead,
)

router = APIRouter(prefix="/payments", tags=["payments"])

#: Une dette se lit, s'ouvre et s'abandonne pour elle-même : son cycle de vie n'est
#: pas celui d'un versement. D'où un second préfixe.
debts_router = APIRouter(prefix="/debts", tags=["debts"])

#: Identifient l'écriture dans `idempotency_keys` : une même clé sur deux endpoints
#: différents est un abus visible, pas un rejeu.
CREATE_PAYMENT_ENDPOINT = "POST /api/v1/payments"
CREATE_DEBT_ENDPOINT = "POST /api/v1/debts"
#: Gabarit : l'identifiant du paiement fait partie de l'endpoint enregistré, pour
#: qu'une même clé présentée pour annuler un **autre** paiement soit refusée au lieu
#: de rejouer la réponse du premier.
CANCEL_PAYMENT_ENDPOINT = "POST /api/v1/payments/{payment_id}/cancel"


@router.get("/{payment_id}/refunded-returns", response_model=list[RefundLinkRead])
def refunded_returns(
    payment_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("payments:read"))],
) -> list[RefundLinkRead]:
    """Retours remboursés par ce versement (T22).

    Un versement peut en couvrir plusieurs : c'est précisément ce que la table de
    lettrage permet, et ce qu'une simple `payments.sale_return_id` interdirait.

    Le paiement est lu d'abord, et non seulement ses lettrages : sans cela, le
    paiement d'une autre entreprise rendrait une liste vide — une réponse qui ne
    ment pas mais qui n'apprend rien. Il rend 404, comme toute ressource d'un autre
    tenant.
    """
    payment = service.get_payment(tenant.session, tenant.ctx, payment_id)
    return [
        RefundLinkRead.model_validate(refund)
        for refund in service.refunds_for_payment(tenant.session, tenant.ctx, payment.id)
    ]


# ------------------------------------------------------------------ paiements


@router.post("", response_model=PaymentDetail, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PaymentCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("payments:create"))],
    idempotency_key: IdempotencyKey,
) -> Response:
    """Encaisse ou décaisse, et impute sur une ou plusieurs dettes (Diagramme 5).

    Le sur-paiement est refusé : ni au-delà du versement (422), ni au-delà du solde
    d'une dette (409). Aucun avoir ni solde créditeur en V1 — le trop-perçu se
    règle en rendant l'argent, pas en le gardant.
    """
    replay = idempotency.reserve(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        endpoint=CREATE_PAYMENT_ENDPOINT,
        payload=payload,
    )
    if replay is not None:
        return idempotency.replay_response(replay)

    payment = service.record_payment(
        tenant.session, tenant.ctx, payload, ip_address=client_ip(request)
    )
    allocations = service.allocations_of_payments(tenant.session, tenant.ctx, [payment.id])
    return idempotency.completed(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        status_code=status.HTTP_201_CREATED,
        model=service.build_payment_detail(payment, allocations.get(payment.id, [])),
    )


@router.get("", response_model=PaymentPage)
def list_payments(
    tenant: Annotated[TenantSession, Depends(require_permission("payments:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    direction: Annotated[CashDirection | None, Query()] = None,
    period_from: Annotated[datetime | None, Query(alias="from")] = None,
    period_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> PaymentPage:
    """Mouvements de caisse, du plus récent au plus ancien."""
    payments, total = service.list_payments(
        tenant.session,
        tenant.ctx,
        page=page,
        page_size=page_size,
        direction=direction,
        period_from=period_from,
        period_to=period_to,
    )
    payment_ids = [payment.id for payment in payments]
    allocations = service.allocations_of_payments(tenant.session, tenant.ctx, payment_ids)
    reversals = service.reversals_of_payments(tenant.session, tenant.ctx, payment_ids)
    return PaymentPage(
        items=[
            service.build_payment_detail(
                payment, allocations.get(payment.id, []), reversals.get(payment.id)
            )
            for payment in payments
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{payment_id}", response_model=PaymentDetail)
def get_payment(
    payment_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("payments:read"))],
) -> PaymentDetail:
    """Détail d'un versement, ses affectations et son éventuelle annulation comprises."""
    payment = service.get_payment(tenant.session, tenant.ctx, payment_id)
    allocations = service.allocations_of_payments(tenant.session, tenant.ctx, [payment.id])
    reversals = service.reversals_of_payments(tenant.session, tenant.ctx, [payment.id])
    return service.build_payment_detail(
        payment, allocations.get(payment.id, []), reversals.get(payment.id)
    )


@router.post(
    "/{payment_id}/cancel", response_model=PaymentDetail, status_code=status.HTTP_201_CREATED
)
def cancel_payment(
    payment_id: UUID,
    payload: PaymentCancel,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("payments:cancel"))],
    idempotency_key: IdempotencyKey,
) -> Response:
    """Annule un paiement erroné par contre-écriture (ADR 0038).

    201 : une écriture est **créée** — l'annulation —, l'origine n'est pas modifiée.
    La réponse est le paiement d'origine, désormais `cancelled: true`. Corriger une
    saisie, c'est annuler puis ressaisir : il n'y a pas de « modifier un paiement ».
    """
    replay = idempotency.reserve(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        endpoint=CANCEL_PAYMENT_ENDPOINT.format(payment_id=payment_id),
        payload=payload,
    )
    if replay is not None:
        return idempotency.replay_response(replay)

    payment, reversal = service.cancel_payment(
        tenant.session,
        tenant.ctx,
        payment_id,
        reason=payload.reason,
        ip_address=client_ip(request),
    )
    allocations = service.allocations_of_payments(tenant.session, tenant.ctx, [payment.id])
    return idempotency.completed(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        status_code=status.HTTP_201_CREATED,
        model=service.build_payment_detail(payment, allocations.get(payment.id, []), reversal),
    )


# --------------------------------------------------------------------- dettes


@debts_router.get("", response_model=DebtPage)
def list_debts(
    tenant: Annotated[TenantSession, Depends(require_permission("debts:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    party_type: Annotated[PartyType | None, Query()] = None,
    debt_status: Annotated[DebtStatus | None, Query(alias="status")] = None,
    overdue: Annotated[bool, Query()] = False,
) -> DebtPage:
    """Créances et dettes, échéance la plus proche en tête."""
    debts, total = service.list_debts(
        tenant.session,
        tenant.ctx,
        page=page,
        page_size=page_size,
        party_type=party_type,
        status=debt_status,
        overdue=overdue,
    )
    allocations = service.allocations_of_debts(
        tenant.session, tenant.ctx, [debt.id for debt in debts]
    )
    return DebtPage(
        items=[service.build_debt_detail(debt, allocations.get(debt.id, [])) for debt in debts],
        page=page,
        page_size=page_size,
        total=total,
    )


@debts_router.post("", response_model=DebtDetail, status_code=status.HTTP_201_CREATED)
def create_debt(
    payload: DebtCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("debts:create"))],
    idempotency_key: IdempotencyKey,
) -> Response:
    """Ouvre une dette à la main : engagement fournisseur, ou créance hors vente.

    Une dette née d'une vente n'entre pas par ici : elle naît de la confirmation.
    """
    replay = idempotency.reserve(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        endpoint=CREATE_DEBT_ENDPOINT,
        payload=payload,
    )
    if replay is not None:
        return idempotency.replay_response(replay)

    debt = service.create_debt(tenant.session, tenant.ctx, payload, ip_address=client_ip(request))
    return idempotency.completed(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        status_code=status.HTTP_201_CREATED,
        model=service.build_debt_detail(debt, []),
    )


@debts_router.get("/{debt_id}", response_model=DebtDetail)
def get_debt(
    debt_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("debts:read"))],
) -> DebtDetail:
    """Détail d'une dette, ses règlements compris."""
    debt = service.get_debt(tenant.session, tenant.ctx, debt_id)
    allocations = service.allocations_of_debts(tenant.session, tenant.ctx, [debt.id])
    return service.build_debt_detail(debt, allocations.get(debt.id, []))


@debts_router.post("/{debt_id}/write-off", response_model=DebtDetail)
def write_off_debt(
    debt_id: UUID,
    payload: DebtWriteOff,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("debts:write_off"))],
) -> DebtDetail:
    """Abandonne une créance. Gérant seul, motif obligatoire, audit critique.

    `debts:write_off` n'appartient qu'au gérant : renoncer à un actif n'est pas une
    écriture comptable de plus. Le montant initial reste lisible — `principal`
    n'est jamais réécrit.
    """
    debt = service.write_off_debt(
        tenant.session,
        tenant.ctx,
        debt_id,
        reason=payload.reason,
        ip_address=client_ip(request),
    )
    allocations = service.allocations_of_debts(tenant.session, tenant.ctx, [debt.id])
    return service.build_debt_detail(debt, allocations.get(debt.id, []))
