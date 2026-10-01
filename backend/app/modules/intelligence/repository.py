"""Requêtes de CoGes Intelligence — filtrées par tenant, sans règle métier.

Les écritures sont toutes idempotentes, et c'est l'index unique qui tranche, jamais un
`SELECT` préalable (ADR 0032) : un rejeu du pipeline sur le même `as_of` met à jour,
il ne duplique pas (**T33**).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    Table,
    and_,
    case,
    func,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.repository import MAX_PAGE_SIZE, TenantRepository
from app.core.tenancy import TenantContext
from app.modules.intelligence.models import Forecast, Insight, MlFeatureSnapshot

FORECASTS_TABLE: Table = Forecast.__table__  # type: ignore[assignment]

#: Un insight « vivant » est affiché ; écarté ou résolu, il ne l'est plus.
LIVE_STATUSES = ("new", "read", "acknowledged")

#: Ordre de lecture des recommandations (ADR 0057) : critique, attention, information. Un
#: `CASE` explicite plutôt que l'ordre de déclaration de l'ENUM `insight_severity`.
SEVERITY_RANK = case(
    (Insight.severity == "critical", 0),
    (Insight.severity == "warning", 1),
    else_=2,
)


def _check_page(page: int, page_size: int) -> None:
    if page < 1:
        raise ValueError("page doit être >= 1")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size doit être entre 1 et {MAX_PAGE_SIZE}")


class SnapshotRepository:
    """Features figées. Clé `(company_id, product_id, as_of)`, pas d'`id` métier."""

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def _select(self) -> Select[tuple[MlFeatureSnapshot]]:
        return select(MlFeatureSnapshot).where(MlFeatureSnapshot.company_id == self.ctx.company_id)

    def insert_once(self, *, product_id: UUID, as_of: dt.date, features: dict[str, Any]) -> bool:
        """Écrit la photographie si elle n'existe pas encore. Jamais de réécriture (§ 6.2).

        Renvoie `True` si la ligne est neuve. Un rejeu laisse l'ancienne intacte : la
        réécrire avec des données arrivées depuis serait exactement la fuite temporelle
        que cette table existe pour empêcher.
        """
        stmt = (
            insert(MlFeatureSnapshot)
            .values(
                company_id=self.ctx.company_id,
                product_id=product_id,
                as_of=as_of,
                features=features,
            )
            .on_conflict_do_nothing(constraint="mlf_uq")
            .returning(MlFeatureSnapshot.id)
        )
        return self.session.execute(stmt).scalar_one_or_none() is not None

    def for_as_of(self, as_of: dt.date) -> Sequence[MlFeatureSnapshot]:
        stmt = self._select().where(MlFeatureSnapshot.as_of == as_of)
        return self.session.execute(stmt.order_by(MlFeatureSnapshot.product_id)).scalars().all()

    def without_labels(self, *, since: dt.date, until: dt.date) -> Sequence[MlFeatureSnapshot]:
        stmt = self._select().where(
            MlFeatureSnapshot.labels.is_(None),
            MlFeatureSnapshot.as_of.between(since, until),
        )
        return self.session.execute(stmt).scalars().all()

    def set_labels(self, snapshot_id: int, labels: dict[str, Any]) -> None:
        """Seule colonne que `coges_analytics` peut mettre à jour (révision 0011)."""
        self.session.execute(
            update(MlFeatureSnapshot)
            .where(
                MlFeatureSnapshot.company_id == self.ctx.company_id,
                MlFeatureSnapshot.id == snapshot_id,
            )
            .values(labels=labels)
        )


class ForecastRepository(TenantRepository[Forecast]):
    """Prévisions : upsert sur `forecasts_idem`, lecture par `forecasts_read`."""

    model = Forecast

    def upsert(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        values = [{"company_id": self.ctx.company_id, **row} for row in rows]
        # La table et non l'entité : la colonne `metadata` porte le nom que la base
        # déclarative réserve à son `MetaData`, et l'ORM la confondrait avec lui.
        stmt = insert(FORECASTS_TABLE).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="forecasts_idem",
            set_={
                "yhat": stmt.excluded.yhat,
                "yhat_lower": stmt.excluded.yhat_lower,
                "yhat_upper": stmt.excluded.yhat_upper,
                "model_name": stmt.excluded.model_name,
                "metadata": stmt.excluded["metadata"],
                "generated_at": func.now(),
            },
        )
        self.session.execute(stmt)
        return len(values)

    def latest_as_of(self) -> dt.date | None:
        """Dernière date de production — sert l'index `forecasts_asof`."""
        stmt = select(func.max(Forecast.as_of)).where(Forecast.company_id == self.ctx.company_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def _latest_filters(
        self, as_of: dt.date, *, product_id: UUID | None, forecast_type: str | None
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = [
            Forecast.company_id == self.ctx.company_id,
            Forecast.as_of == as_of,
        ]
        if product_id is not None:
            filters.append(Forecast.product_id == product_id)
        if forecast_type is not None:
            filters.append(Forecast.forecast_type == forecast_type)
        return filters

    def page_for(
        self,
        as_of: dt.date,
        *,
        product_id: UUID | None,
        forecast_type: str | None,
        page: int,
        page_size: int,
    ) -> Sequence[Forecast]:
        _check_page(page, page_size)
        stmt = (
            select(Forecast)
            .where(*self._latest_filters(as_of, product_id=product_id, forecast_type=forecast_type))
            .order_by(Forecast.product_id, Forecast.forecast_type, Forecast.horizon_date)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def count_for(
        self, as_of: dt.date, *, product_id: UUID | None, forecast_type: str | None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Forecast)
            .where(*self._latest_filters(as_of, product_id=product_id, forecast_type=forecast_type))
        )
        return int(self.session.execute(stmt).scalar_one())

    def summary(self, as_of: dt.date) -> tuple[int, dt.datetime | None]:
        """Produits couverts et date de production du dernier `as_of`."""
        stmt = select(
            func.count(func.distinct(Forecast.product_id)), func.max(Forecast.generated_at)
        ).where(Forecast.company_id == self.ctx.company_id, Forecast.as_of == as_of)
        products, generated = self.session.execute(stmt).one()
        return int(products), generated

    def demand_totals(self, as_of: dt.date, *, horizon_to: dt.date) -> list[dict[str, Any]]:
        """Quantité prévue cumulée par produit sur l'horizon, bornes cumulées comprises."""
        stmt = (
            select(
                Forecast.product_id,
                func.sum(Forecast.yhat).label("total"),
                func.sum(Forecast.yhat_lower).label("lower"),
                func.sum(Forecast.yhat_upper).label("upper"),
                func.max(Forecast.model_name).label("model_name"),
                func.max(Forecast.model_version).label("model_version"),
                func.max(Forecast.metadata_["product_name"].astext).label("product_name"),
                func.max(Forecast.generated_at).label("generated_at"),
            )
            .where(
                Forecast.company_id == self.ctx.company_id,
                Forecast.as_of == as_of,
                Forecast.forecast_type == "demand_qty",
                Forecast.product_id.is_not(None),
                Forecast.horizon_date <= horizon_to,
            )
            .group_by(Forecast.product_id)
        )
        return [dict(row._mapping) for row in self.session.execute(stmt)]


class InsightRepository(TenantRepository[Insight]):
    """Insights : upsert sur l'index partiel `insights_dedupe_uq`."""

    model = Insight

    def upsert(self, draft: dict[str, Any]) -> tuple[UUID, bool]:
        """Insère, ou met à jour l'insight vivant de même `dedupe_key`.

        Renvoie `(id, inséré)`. L'index est partiel (`status <> 'dismissed'`) : un
        insight écarté ne bloque pas la réémission, qui crée une ligne neuve (**T34**).
        Un insight **résolu** qui réapparaît redevient `new` — le problème est revenu.
        Le statut d'un insight vivant, lui, n'est pas touché : le gérant qui l'a lu ne
        le retrouve pas « nouveau » à chaque nuit.
        """
        base = insert(Insight).values(company_id=self.ctx.company_id, **draft)
        reopened = Insight.status == "resolved"
        stmt: Any = base.on_conflict_do_update(
            index_elements=[Insight.company_id, Insight.dedupe_key],
            index_where=text("status <> 'dismissed'"),
            set_={
                "severity": base.excluded.severity,
                "title": base.excluded.title,
                "body": base.excluded.body,
                "evidence": base.excluded.evidence,
                "model_name": base.excluded.model_name,
                "model_version": base.excluded.model_version,
                "valid_until": base.excluded.valid_until,
                "generated_at": func.now(),
                "status": _case(reopened, literal_column("'new'::insight_status"), Insight.status),
                "read_at": _case(reopened, literal_column("NULL::timestamptz"), Insight.read_at),
                "resolved_at": _case(
                    reopened, literal_column("NULL::timestamptz"), Insight.resolved_at
                ),
            },
        ).returning(Insight.id, literal_column("(xmax = 0)").label("inserted"))
        row = self.session.execute(stmt).one()
        return row.id, bool(row.inserted)

    def resolve_live(self, *, insight_type: str, keep: Sequence[str], now: dt.datetime) -> int:
        """Résout les insights vivants d'un type dont la clé n'a pas été réémise."""
        stmt = text(
            """
            UPDATE insights
               SET status = 'resolved', resolved_at = :now,
                   read_at = COALESCE(read_at, :now)
             WHERE company_id = :company_id
               AND insight_type = CAST(:insight_type AS insight_type)
               AND status IN ('new', 'read', 'acknowledged')
               AND NOT (dedupe_key = ANY(CAST(:keep AS text[])))
            """
        )
        result = self.session.execute(
            stmt,
            {
                "now": now,
                "company_id": self.ctx.company_id,
                "insight_type": insight_type,
                "keep": list(keep),
            },
        )
        return int(getattr(result, "rowcount", 0) or 0)

    def _visible(
        self,
        *,
        now: dt.datetime,
        status: str | None,
        severity: str | None,
        insight_type: str | None,
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = [
            Insight.company_id == self.ctx.company_id,
            or_(Insight.valid_until.is_(None), Insight.valid_until > now),
        ]
        if status is not None:
            filters.append(Insight.status == status)
        else:
            filters.append(Insight.status.in_(LIVE_STATUSES))
        if severity is not None:
            filters.append(Insight.severity == severity)
        if insight_type is not None:
            filters.append(Insight.insight_type == insight_type)
        return filters

    def page_visible(
        self,
        *,
        now: dt.datetime,
        status: str | None,
        severity: str | None,
        insight_type: str | None,
        page: int,
        page_size: int,
    ) -> Sequence[Insight]:
        _check_page(page, page_size)
        stmt = (
            select(Insight)
            .where(
                *self._visible(now=now, status=status, severity=severity, insight_type=insight_type)
            )
            .order_by(SEVERITY_RANK, Insight.generated_at.desc(), Insight.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def count_visible(
        self,
        *,
        now: dt.datetime,
        status: str | None,
        severity: str | None,
        insight_type: str | None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Insight)
            .where(
                *self._visible(now=now, status=status, severity=severity, insight_type=insight_type)
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def live_counts(self, *, now: dt.datetime, column: str) -> dict[str, int]:
        """Insights vivants comptés par type ou par gravité."""
        grouped = Insight.insight_type if column == "insight_type" else Insight.severity
        stmt = (
            select(grouped, func.count())
            .where(*self._visible(now=now, status=None, severity=None, insight_type=None))
            .group_by(grouped)
        )
        return {str(key): int(count) for key, count in self.session.execute(stmt).all()}

    def live_for_entity(
        self, *, insight_type: str, entity_id: UUID, now: dt.datetime
    ) -> Insight | None:
        stmt = (
            self._select()
            .where(
                *self._visible(now=now, status=None, severity=None, insight_type=insight_type),
                and_(Insight.entity_table == "products", Insight.entity_id == entity_id),
            )
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_for_update(self, insight_id: UUID) -> Insight | None:
        stmt = self._select().where(Insight.id == insight_id).with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()


def _case(condition: ColumnElement[bool], then: Any, otherwise: Any) -> Any:
    return case((condition, then), else_=otherwise)
