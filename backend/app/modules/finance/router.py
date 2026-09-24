"""Routes HTTP du module Finance. Aucune requête SQL ici.

Une seule route en phase 06, et elle répond à une question précise du § 5.4 : « quel
retour a provoqué cette sortie de trésorerie ». L'autre sens — d'un retour vers ses
remboursements — est rendu par Sales, qui possède les retours.

Pourquoi ici plutôt que dans Sales : la ressource interrogée est un **paiement**, et
les paiements appartiennent à Finance. La réponse ne porte donc que des lettrages,
sans numéro de retour : Finance est sous Sales dans l'ordre des dépendances et ne
l'importe jamais. Le frontend qui veut un `return_no` suit le `sale_return_id`.

Les écritures financières autonomes — encaisser, affecter, dépenser — arrivent en
phase 07. Une façade sans endpoint d'écriture est une information utile (ADR 0019).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.deps import TenantSession, require_permission
from app.modules.finance import service
from app.modules.finance.schemas import RefundLinkRead

router = APIRouter(prefix="/payments", tags=["payments"])


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
