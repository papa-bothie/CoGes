"""Schémas du module Dashboard."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.money import Amount, Quantity
from app.modules.finance.schemas import DebtStatus
from app.modules.inventory.schemas import StockStatus
from app.modules.notifications.schemas import NotificationSeverity
from app.modules.sales.schemas import SaleStatus

#: Profondeur de la courbe d'accueil, en jours.
REVENUE_TREND_DAYS = 30

#: Nombre de ventes récentes affichées.
RECENT_SALES = 5

#: Nombre d'alertes actives affichées.
ACTIVE_ALERTS = 5

#: Articles de la carte « À surveiller » (maquette v2, écran 01) : deux, puis la dette.
WATCH_STOCK = 2


class RevenuePoint(BaseModel):
    """Un jour de chiffre d'affaires net, dans le fuseau de l'entreprise."""

    model_config = ConfigDict(extra="forbid")

    day: date
    net_revenue: Amount


class RecentSale(BaseModel):
    """Une vente récente, réduite à ce qu'une liste d'accueil montre."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    sale_no: str
    customer_name: str | None
    total: Amount
    sold_at: datetime
    #: De quoi poser le badge « Payé », « Reste X F », « Retour » (ADR 0070).
    status: SaleStatus
    balance: Amount
    debt_status: DebtStatus | None
    has_returns: bool
    returned_total: Amount


class WatchStock(BaseModel):
    """Un article à surveiller : sous son seuil ou épuisé (« Plus que 2 sacs »)."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    name: str
    unit: str
    qty_on_hand: Quantity
    status: StockStatus


class WatchDebt(BaseModel):
    """Le client qui doit le plus, et depuis quand (« Doit 25 000 F depuis 12 jours »)."""

    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    customer_name: str
    balance: Amount
    #: Jours écoulés depuis sa plus ancienne dette ouverte, dans le fuseau de l'entreprise.
    days: int


class ActiveAlert(BaseModel):
    """Une alerte non lue de l'utilisateur courant."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    type: str
    #: Dérivée du type par le module Notifications (ADR 0059) : couleur du bandeau.
    severity: NotificationSeverity
    title: str
    created_at: datetime


class Dashboard(BaseModel):
    """L'écran d'accueil, en une réponse.

    Les mesures **hors taxe** portent le nom que leur donne le § 4.10 ; la marge est
    « estimée » parce qu'elle ignore amortissements et provisions — c'est la question
    du gérant, pas celle de son expert-comptable (décision 09).
    """

    model_config = ConfigDict(extra="forbid")

    #: Jour et mois de référence, dans le fuseau de l'entreprise.
    today: date
    month_from: date
    month_to: date

    revenue_today: Amount
    revenue_month: Amount
    #: `null` sans `analytics:read` (ADR 0030, 0087).
    estimated_margin_month: Amount | None
    sales_today: int
    #: `null` sans `debts:read` (ADR 0072, 0087), comme le nombre et `watch_debt`.
    receivables_open: Amount | None
    #: Nombre de clients qui doivent encore quelque chose (« 5 clients »).
    receivables_customer_count: int | None
    stock_alert_count: int
    #: Dans la caisse : tout ce qui est entré moins tout ce qui est sorti, depuis le début,
    #: paiements vivants seulement, compensations exclues (ADR 0024, ADR 0070). Aucun fond
    #: de caisse de départ en V1. `null` sans `analytics:read`, le droit de `/analytics/cash`.
    cash_on_hand: Amount | None
    #: Carte « À surveiller » : articles les plus bas, puis la plus grosse dette client.
    watch_stock: list[WatchStock]
    watch_debt: WatchDebt | None

    revenue_trend: list[RevenuePoint]
    recent_sales: list[RecentSale]
    active_alerts: list[ActiveAlert]

    #: Instant de composition, pour que l'interface puisse dire « il y a 12 s ».
    computed_at: datetime
    #: Vrai quand la réponse sort du cache court (décision 14).
    cached: bool = False
