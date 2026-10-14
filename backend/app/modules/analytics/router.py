"""Routes HTTP du module Analytics. Aucune requête SQL ici.

Des routes en lecture seule et toutes servies par des agrégats **déjà
calculés** : l'état de l'argent sur une période, un classement de produits pour une
métrique nommée, une série journalière. Aucun calcul long dans une requête HTTP.

La permission est `analytics:read`, que le gérant et le comptable possèdent — pas le
vendeur : une caisse encaisse, elle n'a pas à lire la marge de l'entreprise.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.deps import TenantSession, require_permission
from app.core.errors import PermissionDeniedError
from app.core.repository import MAX_PAGE_SIZE
from app.modules.analytics import service
from app.modules.analytics.schemas import (
    MAX_RANKING_LIMIT,
    PEOPLE_PAGE_SIZE,
    CashJournal,
    CustomerSalePage,
    CustomerSheet,
    ExpensesSummary,
    FinanceOverview,
    MoneyOverview,
    MoneyPeriod,
    PeoplePage,
    PersonPaymentPage,
    ProductHistory,
    ProductMetric,
    ProductRanking,
    SupplierDeliveryPage,
    SupplierSheet,
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


# ------------------------------------------------------------- l'argent (écrans 17 à 21)


@router.get("/money", response_model=MoneyOverview)
def money_overview(
    tenant: Annotated[TenantSession, Depends(require_permission("analytics:read"))],
    period: Annotated[MoneyPeriod | None, Query()] = None,
    period_from: Annotated[date | None, Query(alias="from")] = None,
    period_to: Annotated[date | None, Query(alias="to")] = None,
) -> MoneyOverview:
    """Écran 17 « L'argent » : gagné ou perdu, la caisse et son graphique, ce qui est dû.

    `period` (aujourd'hui, les 7 derniers jours, le mois en cours) ou bien `from` et
    `to` (« Choisir des dates »). Les cartes de ce qui est dû sont `null` sans
    `debts:read` (ADR 0073).
    """
    return service.money_overview(
        tenant.session, tenant.ctx, period=period, period_from=period_from, period_to=period_to
    )


@router.get("/cash", response_model=CashJournal)
def cash_journal(
    tenant: Annotated[TenantSession, Depends(require_permission("analytics:read"))],
    day: Annotated[date | None, Query()] = None,
) -> CashJournal:
    """Écran 21 « Entrées et sorties » d'un jour (aujourd'hui par défaut).

    `analytics:read` comme l'écran 17 : la caisse nomme les dépenses, que le vendeur
    ne lit pas.

    Les paiements annulés et leurs annulations sont listés, jamais comptés : rien ne
    s'efface (ADR 0038). Les compensations, qui ne touchent pas la caisse, sont écartées.
    """
    return service.cash_journal(tenant.session, tenant.ctx, day=day)


@router.get("/expenses-summary", response_model=ExpensesSummary)
def expenses_summary(
    tenant: Annotated[TenantSession, Depends(require_permission("expenses:read"))],
    period_from: Annotated[date | None, Query(alias="from")] = None,
    period_to: Annotated[date | None, Query(alias="to")] = None,
) -> ExpensesSummary:
    """Écran 20, à droite : les dépenses par type (le mois en cours par défaut) et les
    cinq dernières, avec leur moyen de paiement."""
    return service.expenses_summary(
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


@router.get("/products/{product_id}/history", response_model=ProductHistory)
def product_history(
    product_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("inventory:read"))],
) -> ProductHistory:
    """« Ce qui s'est passé » sur la fiche d'un article : ventes, livraisons, retours et
    corrections, avec le client, le fournisseur ou la raison (ADR 0071)."""
    return service.product_history(tenant.session, tenant.ctx, product_id)


# ------------------------------------------- clients et fournisseurs (écrans 13 à 16)
#
# Lisibles par qui lit les personnes (le vendeur aussi) ; les montants dus ne sortent
# qu'avec `debts:read` (ADR 0072). Ce qui ne parle que d'argent dû l'exige d'entrée.

Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Search = Annotated[str | None, Query(max_length=120)]


def _require_money(tenant: TenantSession) -> None:
    if not tenant.ctx.has_permission(service.MONEY_PERMISSION):
        raise PermissionDeniedError(details={"permission": service.MONEY_PERMISSION})


@router.get("/customers", response_model=PeoplePage)
def customers(
    tenant: Annotated[TenantSession, Depends(require_permission("customers:read"))],
    owing: Annotated[bool, Query()] = False,
    search: Search = None,
    page: Page = 1,
    page_size: PageSize = PEOPLE_PAGE_SIZE,
) -> PeoplePage:
    """Liste des clients : qui vous doit d'abord, puis la dernière visite (écran 13)."""
    if owing:
        _require_money(tenant)
    return service.list_people(
        tenant.session,
        tenant.ctx,
        kind="customer",
        owing=owing,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get("/customers/{customer_id}", response_model=CustomerSheet)
def customer_sheet(
    customer_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("customers:read"))],
) -> CustomerSheet:
    """Tuiles de la fiche client : sa dette, ses achats du mois, sa dernière visite."""
    return service.customer_sheet(tenant.session, tenant.ctx, customer_id)


@router.get("/customers/{customer_id}/sales", response_model=CustomerSalePage)
def customer_sales(
    customer_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("sales:read"))],
    page: Page = 1,
    page_size: PageSize = PEOPLE_PAGE_SIZE,
) -> CustomerSalePage:
    """« Ses achats » : ses ventes avec leurs premiers articles."""
    return service.customer_sales(
        tenant.session, tenant.ctx, customer_id, page=page, page_size=page_size
    )


@router.get("/customers/{customer_id}/payments", response_model=PersonPaymentPage)
def customer_payments(
    customer_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("payments:read"))],
    page: Page = 1,
    page_size: PageSize = PEOPLE_PAGE_SIZE,
) -> PersonPaymentPage:
    """« Ses paiements » : à la vente ou sur une dette."""
    return service.customer_payments(
        tenant.session, tenant.ctx, customer_id, page=page, page_size=page_size
    )


@router.get("/suppliers", response_model=PeoplePage)
def suppliers(
    tenant: Annotated[TenantSession, Depends(require_permission("suppliers:read"))],
    owing: Annotated[bool, Query()] = False,
    search: Search = None,
    page: Page = 1,
    page_size: PageSize = PEOPLE_PAGE_SIZE,
) -> PeoplePage:
    """Liste des fournisseurs : à qui vous devez d'abord, puis la dernière livraison."""
    if owing:
        _require_money(tenant)
    return service.list_people(
        tenant.session,
        tenant.ctx,
        kind="supplier",
        owing=owing,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get("/suppliers/{supplier_id}", response_model=SupplierSheet)
def supplier_sheet(
    supplier_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("suppliers:read"))],
) -> SupplierSheet:
    """Tuiles de la fiche fournisseur : ce que vous lui devez, ses livraisons, ses articles."""
    return service.supplier_sheet(tenant.session, tenant.ctx, supplier_id)


@router.get("/suppliers/{supplier_id}/deliveries", response_model=SupplierDeliveryPage)
def supplier_deliveries(
    supplier_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("debts:read"))],
    page: Page = 1,
    page_size: PageSize = PEOPLE_PAGE_SIZE,
) -> SupplierDeliveryPage:
    """« Ses livraisons » : chaque dette fournisseur et ses principaux articles."""
    return service.supplier_deliveries(
        tenant.session, tenant.ctx, supplier_id, page=page, page_size=page_size
    )


@router.get("/suppliers/{supplier_id}/payments", response_model=PersonPaymentPage)
def supplier_payments(
    supplier_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("payments:read"))],
    page: Page = 1,
    page_size: PageSize = PEOPLE_PAGE_SIZE,
) -> PersonPaymentPage:
    """« Vos paiements » : ce que vous lui avez versé."""
    return service.supplier_payments(
        tenant.session, tenant.ctx, supplier_id, page=page, page_size=page_size
    )
