"""Schémas du module Dashboard."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.money import Amount
from app.modules.notifications.schemas import NotificationSeverity

#: Profondeur de la courbe d'accueil, en jours.
REVENUE_TREND_DAYS = 30

#: Nombre de ventes récentes affichées.
RECENT_SALES = 5

#: Nombre d'alertes actives affichées.
ACTIVE_ALERTS = 5


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
    estimated_margin_month: Amount
    sales_today: int
    receivables_open: Amount
    stock_alert_count: int

    revenue_trend: list[RevenuePoint]
    recent_sales: list[RecentSale]
    active_alerts: list[ActiveAlert]

    #: Instant de composition, pour que l'interface puisse dire « il y a 12 s ».
    computed_at: datetime
    #: Vrai quand la réponse sort du cache court (décision 14).
    cached: bool = False
