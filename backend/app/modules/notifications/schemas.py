"""Schémas du module Notifications."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field


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
    #: Échecs de connexion répétés sur un compte réel (ADR 0078, révision 0022).
    LOGIN_FAILURES = "login_failures"


class NotificationSeverity(StrEnum):
    """Gravité d'une alerte, **dérivée de son type** par le serveur (ADR 0059).

    Le front en tire la couleur d'un bandeau ; il ne la devine jamais lui-même.
    """

    WARNING = "warning"
    CRITICAL = "critical"


#: Ce qui bloque une vente ou signale un risque critique ; tout le reste demande attention.
CRITICAL_TYPES = frozenset({NotificationType.STOCK_OUT, NotificationType.INSIGHT_CRITICAL})


def severity_of(notification_type: str) -> NotificationSeverity:
    """Gravité d'un type d'alerte : `critical` pour une rupture ou un insight critique."""
    return (
        NotificationSeverity.CRITICAL
        if notification_type in CRITICAL_TYPES
        else NotificationSeverity.WARNING
    )


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> NotificationSeverity:
        return severity_of(self.type)


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
    #: Dont les alertes graves (`critical`) : seules elles allument le badge de la cloche
    #: (maquette v2, ADR 0070).
    critical: int
