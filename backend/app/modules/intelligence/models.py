"""Tables de CoGes Intelligence (§ 8.9) : features figées, prévisions, insights.

Colonnes, rien d'autre. Les trois tables sont écrites par le pipeline sous
`coges_analytics` ; l'application (`coges_app`) ne lit que `forecasts` et `insights`
et ne peut modifier que `insights.status` et ses deux horodatages (révision 0011).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, Identity, Numeric, Text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import NOW, IdentifiedTenantBase, TenantBase

FORECAST_TYPE = PG_ENUM(
    "demand_qty",
    "revenue",
    "stockout_date",
    "cash_balance",
    name="forecast_type",
    create_type=False,
)
INSIGHT_TYPE = PG_ENUM(
    "stockout_risk",
    "slow_mover",
    "demand_spike",
    "margin_drop",
    "expense_anomaly",
    "cash_shortfall",
    "debt_overdue",
    "cashier_anomaly",
    "insufficient_history",
    name="insight_type",
    create_type=False,
)
INSIGHT_SEVERITY = PG_ENUM(
    "info", "warning", "critical", name="insight_severity", create_type=False
)
INSIGHT_STATUS = PG_ENUM(
    "new", "read", "acknowledged", "dismissed", "resolved", name="insight_status", create_type=False
)


class MlFeatureSnapshot(TenantBase):
    """Features d'un produit **telles qu'elles étaient connues** au soir de `as_of`.

    Écrite une fois, jamais réécrite (§ 6.2) ; seuls les labels, connus plus tard, se
    complètent. Jamais lue par l'application.
    """

    __tablename__ = "ml_feature_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    as_of: Mapped[dt.date] = mapped_column(Date)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)
    labels: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=NOW)


class Forecast(IdentifiedTenantBase):
    """Une valeur prévue, datée, avec le modèle qui l'a produite (§ 4.11)."""

    __tablename__ = "forecasts"

    product_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    forecast_type: Mapped[str] = mapped_column(FORECAST_TYPE)
    as_of: Mapped[dt.date] = mapped_column(Date)
    horizon_date: Mapped[dt.date] = mapped_column(Date)
    yhat: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    yhat_lower: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    yhat_upper: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    model_name: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    generated_at: Mapped[dt.datetime] = mapped_column(server_default=NOW)


class Insight(IdentifiedTenantBase):
    """Un fait analytique daté, qui garde son évidence même lu (§ 4.12)."""

    __tablename__ = "insights"

    insight_type: Mapped[str] = mapped_column(INSIGHT_TYPE)
    severity: Mapped[str] = mapped_column(INSIGHT_SEVERITY)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_table: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(INSIGHT_STATUS, server_default="new")
    read_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    generated_at: Mapped[dt.datetime] = mapped_column(server_default=NOW)
    valid_until: Mapped[dt.datetime | None] = mapped_column(nullable=True)
