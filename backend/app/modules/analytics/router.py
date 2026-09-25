"""Routes HTTP du module Analytics. Aucune requête SQL ici.

Trois routes, toutes en lecture seule et toutes servies par des agrégats **déjà
calculés** : l'état de l'argent sur une période, un classement de produits pour une
métrique nommée, une série journalière. Aucun calcul long dans une requête HTTP.

La permission est `analytics:read`, que le gérant et le comptable possèdent — pas le
vendeur : une caisse encaisse, elle n'a pas à lire la marge de l'entreprise.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import TenantSession, require_permission
from app.modules.analytics import service
from app.modules.analytics.schemas import (
    MAX_RANKING_LIMIT,
    FinanceOverview,
    ProductMetric,
    ProductRanking,
    Timeseries,
    TimeseriesMeasure,
)

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


@router.get("/products", response_model=ProductRanking)
def product_ranking(
    tenant: Annotated[TenantSession, Depends(require_permission("analytics:read"))],
    metric: Annotated[ProductMetric, Query()],
    period_from: Annotated[date, Query(alias="from")],
    period_to: Annotated[date, Query(alias="to")],
    limit: Annotated[int, Query(ge=1, le=MAX_RANKING_LIMIT)] = 10,
) -> ProductRanking:
    """Classement des produits pour **une** métrique, nommée dans la réponse.

    `metric` est obligatoire et scalaire : il n'existe pas de « meilleur produit »,
    seulement un produit qui génère le plus de marge, ou qui tourne le plus vite
    (décision 12). La métrique `future_potential` répond qu'elle arrive en phase 09
    plutôt que d'inventer une valeur.
    """
    return service.product_ranking(
        tenant.session,
        tenant.ctx,
        metric=metric,
        period_from=period_from,
        period_to=period_to,
        limit=limit,
    )


@router.get("/timeseries", response_model=Timeseries)
def timeseries(
    tenant: Annotated[TenantSession, Depends(require_permission("analytics:read"))],
    measure: Annotated[TimeseriesMeasure, Query()],
    period_from: Annotated[date, Query(alias="from")],
    period_to: Annotated[date, Query(alias="to")],
) -> Timeseries:
    """Série journalière du chiffre d'affaires net ou de la marge brute."""
    return service.timeseries(
        tenant.session,
        tenant.ctx,
        measure=measure,
        period_from=period_from,
        period_to=period_to,
    )
