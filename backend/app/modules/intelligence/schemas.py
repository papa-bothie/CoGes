"""Schémas de CoGes Intelligence : ce que l'API sert, et rien qu'elle calcule.

Chaque élément renvoyé se qualifie lui-même (décisions 12 et 13) : la mesure qu'il
porte (`metric_name`), sa valeur, sa date de production, le modèle et sa version,
son incertitude — ou `insufficient_data: true`, jamais une valeur inventée.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InsightType(StrEnum):
    """Types d'insight de l'ENUM `insight_type`, dont les six que la V1 produit."""

    STOCKOUT_RISK = "stockout_risk"
    SLOW_MOVER = "slow_mover"
    DEMAND_SPIKE = "demand_spike"
    MARGIN_DROP = "margin_drop"
    EXPENSE_ANOMALY = "expense_anomaly"
    CASH_SHORTFALL = "cash_shortfall"
    DEBT_OVERDUE = "debt_overdue"
    CASHIER_ANOMALY = "cashier_anomaly"
    #: Écart assumé à l'ENUM du § 8.1 (révision 0011, ADR 0037).
    INSUFFICIENT_HISTORY = "insufficient_history"


class InsightSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class InsightStatus(StrEnum):
    NEW = "new"
    READ = "read"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class ForecastType(StrEnum):
    """Les deux prévisions que la V1 produit, parmi les quatre de l'ENUM."""

    DEMAND_QTY = "demand_qty"
    STOCKOUT_DATE = "stockout_date"


#: Libellé exact et unité de ce que mesure chaque prévision.
FORECAST_LABELS: dict[ForecastType, tuple[str, str]] = {
    ForecastType.DEMAND_QTY: ("Quantité vendue prévue", "unité/jour"),
    ForecastType.STOCKOUT_DATE: ("Jours avant rupture prévue", "jour"),
}


class Uncertainty(BaseModel):
    """Intervalle quand le modèle en produit un, et qualificatif lisible."""

    model_config = ConfigDict(extra="forbid")

    lower: str | None = None
    upper: str | None = None
    #: `faible`, `moyenne`, `élevée` — figé par le pipeline, jamais recalculé ici.
    level: str | None = None


class InsightRead(BaseModel):
    """Un insight, avec sa métrique nommée et son évidence."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    insight_type: InsightType
    severity: InsightSeverity
    status: InsightStatus
    title: str
    body: str | None
    entity_table: str | None
    entity_id: UUID | None
    metric_name: str | None
    value: str | None
    unit: str | None
    computed_at: datetime
    model_name: str | None
    model_version: str | None
    uncertainty: Uncertainty | None
    insufficient_data: bool
    evidence: dict[str, Any]
    read_at: datetime | None
    resolved_at: datetime | None
    valid_until: datetime | None


class InsightPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    items: list[InsightRead]
    page: int
    page_size: int
    total: int


class InsightStatusChange(StrEnum):
    """Statuts qu'un utilisateur peut poser. Revenir à `new` n'a pas de sens : un
    insight lu l'a été."""

    READ = "read"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class InsightStatusUpdate(BaseModel):
    """Seul `status` est modifiable (§ 4.12)."""

    model_config = ConfigDict(extra="forbid")

    status: InsightStatusChange


class ForecastRead(BaseModel):
    """Une valeur prévue, qualifiée."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    product_id: UUID | None
    product_name: str | None
    forecast_type: ForecastType
    metric_name: str
    unit: str
    as_of: date
    horizon_date: date
    value: str
    uncertainty: Uncertainty
    computed_at: datetime
    model_name: str
    model_version: str


class ForecastPage(BaseModel):
    """Prévisions du dernier `as_of` produit.

    `insufficient_data` vaut `true` quand le produit demandé est sous le seuil
    d'historique : la liste est alors vide, et c'est une réponse, pas une panne.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    insufficient_data: bool
    items: list[ForecastRead]
    page: int
    page_size: int
    total: int


class IntelligenceSummary(BaseModel):
    """Compteurs de l'écran Insights, lus sur les résultats déjà persistés."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    last_as_of: date | None
    computed_at: datetime | None
    insights_by_type: dict[str, int]
    insights_by_severity: dict[str, int]
    forecast_products: int
    insufficient_data_products: int


class FuturePotentialRow(BaseModel):
    """Une ligne de la métrique 8, pour le classement d'Analytics."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    product_name: str
    value: str
    lower: str | None
    upper: str | None
    model_name: str
    model_version: str


class FuturePotential(BaseModel):
    """Potentiel futur estimé : quantité prévue sur l'horizon, par produit."""

    model_config = ConfigDict(extra="forbid")

    as_of: date
    horizon_days: int
    computed_at: datetime
    rows: list[FuturePotentialRow]
