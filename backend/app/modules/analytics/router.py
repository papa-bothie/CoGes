"""Routes HTTP du module Analytics. Aucune requête SQL ici.

Une seule route en phase 07 : l'état de l'argent sur une période. La permission
est `analytics:read`, que le gérant et le comptable possèdent — pas le vendeur :
une caisse encaisse, elle n'a pas à lire la marge de l'entreprise.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import TenantSession, require_permission
from app.modules.analytics import service
from app.modules.analytics.schemas import FinanceOverview

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=FinanceOverview)
def finance_overview(
    tenant: Annotated[TenantSession, Depends(require_permission("analytics:read"))],
    period_from: Annotated[date, Query(alias="from")],
    period_to: Annotated[date, Query(alias="to")],
) -> FinanceOverview:
    """Trésorerie, marge estimée et encours de la période.

    Les deux bornes sont **obligatoires** : un agrégat sans période est une
    requête sur tout l'historique, et personne ne pilote une entreprise sur « tout
    l'historique ».
    """
    return service.finance_overview(
        tenant.session, tenant.ctx, period_from=period_from, period_to=period_to
    )
