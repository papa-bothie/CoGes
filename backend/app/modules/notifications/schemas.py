"""Schémas du module Notifications."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationType(StrEnum):
    """Liste **fermée**, identique au `CHECK` de `notifications.type` (§ 8.8).

    Les deux dernières valeurs appartiennent à CoGes Intelligence (phase 09) ; elles
    figurent ici parce que le `CHECK` les porte déjà, et qu'une énumération qui
    diverge de la base est un 500 qui attend son heure.
    """

    STOCK_LOW = "stock_low"
    STOCK_OUT = "stock_out"
    DEBT_DUE = "debt_due"
    SALE_CANCELLED = "sale_cancelled"
    FORECAST_ALERT = "forecast_alert"
    INSIGHT_CRITICAL = "insight_critical"


class NotificationRead(BaseModel):
    """Une alerte, telle que le fil la présente."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    type: NotificationType
    title: str
    body: str | None
    data: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    """Page de fil d'alertes, les plus récentes d'abord."""

    model_config = ConfigDict(extra="forbid")

    items: list[NotificationRead]
    page: int
    page_size: int
    total: int


class NotificationUpdate(BaseModel):
    """Marquer comme lue, ou revenir en non lu.

    `read` est un booléen explicite plutôt qu'une action implicite : rendre une alerte
    à l'état non lu est un besoin réel — on ouvre par erreur, on veut y revenir.
    """

    model_config = ConfigDict(extra="forbid")

    read: bool


class UnreadCount(BaseModel):
    """Compteur de non-lus de l'utilisateur courant."""

    model_config = ConfigDict(extra="forbid")

    unread: int
