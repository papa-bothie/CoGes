"""Étape 06 : inférence quotidienne ⇒ `forecasts`.

Ne lit que les photographies figées de `as_of` et l'artefact de la semaine : aucune
donnée transactionnelle, donc aucune fuite possible. Écrit en
`ON CONFLICT DO UPDATE` sur `forecasts_idem` — un rejeu met à jour (**T33**).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.intelligence.estimators import baseline, seasonal
from app.modules.intelligence.estimators.artifacts import ArtifactStore
from app.modules.intelligence.models import MlFeatureSnapshot
from app.modules.intelligence.pipelines.common import (
    to_decimal,
    uncertainty_level,
    week_version,
)
from app.modules.intelligence.pipelines.train import train
from app.modules.intelligence.repository import ForecastRepository

#: Horizon publié de la demande, jour par jour.
DEMAND_HORIZON_DAYS = 14
#: Horizon de recherche d'une rupture : au-delà, aucune prévision de rupture.
STOCKOUT_HORIZON_DAYS = 28

type Predictor = Callable[[date], tuple[float, float, float]]


@dataclass(frozen=True)
class StockoutForecast:
    """Rupture prévue d'un produit : jours avant rupture et bornes en jours."""

    days: int
    earliest: int
    latest: int | None
    on_hand: Decimal
    daily_demand: Decimal
    model_name: str
    model_version: str
    level: str


@dataclass
class InferRun:
    as_of: date
    forecast_rows: int = 0
    products: int = 0
    seasonal_products: int = 0
    baseline_products: int = 0
    insufficient: int = 0
    stockouts: dict[UUID, StockoutForecast] = field(default_factory=dict)
    models: dict[UUID, tuple[str, str]] = field(default_factory=dict)


def _load_fits(
    session: Session, ctx: TenantContext, *, as_of: date, store: ArtifactStore
) -> tuple[dict[str, Any], str]:
    version = week_version(as_of)
    artifact = store.load(ctx.company_id, seasonal.MODEL_NAME, version)
    if artifact is None:
        # Première inférence de la semaine sans entraînement : on entraîne ici, dans
        # le worker. Jamais dans l'API (décision 11).
        train(session, ctx, as_of=as_of, store=store)
        artifact = store.load(ctx.company_id, seasonal.MODEL_NAME, version) or {"products": {}}
    path = str(store.path(ctx.company_id, seasonal.MODEL_NAME, version))
    products: dict[str, Any] = artifact.get("products", {})
    return products, path


def _first_crossing(cumulative: list[float], threshold: float) -> int | None:
    for offset, total in enumerate(cumulative, start=1):
        if total >= threshold:
            return offset
    return None


def infer(
    session: Session,
    ctx: TenantContext,
    *,
    as_of: date,
    snapshots: list[MlFeatureSnapshot],
    store: ArtifactStore,
) -> InferRun:
    """Prévisions de demande (J+1 à J+14) et de rupture, par produit suffisant."""
    fits, artifact_path = _load_fits(session, ctx, as_of=as_of, store=store)
    version = week_version(as_of)
    run = InferRun(as_of=as_of)
    rows: list[dict[str, Any]] = []

    for snapshot in snapshots:
        features = snapshot.features
        if not features.get("sufficient"):
            run.insufficient += 1
            continue

        fit_payload = fits.get(str(snapshot.product_id))
        predict: Predictor
        meta: dict[str, Any] = {
            "product_name": features.get("product_name"),
            "features_as_of": as_of.isoformat(),
        }
        if fit_payload is not None:
            fit = seasonal.SeasonalFit.from_json(fit_payload)
            predict = fit.predict
            model_name, model_version = seasonal.MODEL_NAME, version
            meta |= {"artifact_path": artifact_path, "n_obs": fit.n_obs, "r2": round(fit.r2, 4)}
            run.seasonal_products += 1
        else:
            reference = baseline.Baseline(
                mean=float(features["mean_prior_28d"]),
                std=float(features["std_prior_28d"]),
                n_obs=int(features["observable_prior_28d"]),
            )

            def predict(
                _: date, reference: baseline.Baseline = reference
            ) -> tuple[float, float, float]:
                return reference.predict()

            model_name, model_version = baseline.MODEL_NAME, baseline.MODEL_VERSION
            meta |= {"window_days": baseline.WINDOW_DAYS, "n_obs": reference.n_obs}
            run.baseline_products += 1

        run.products += 1
        run.models[snapshot.product_id] = (model_name, model_version)
        horizon = [as_of + timedelta(days=offset) for offset in range(1, STOCKOUT_HORIZON_DAYS + 1)]
        predictions = [predict(day) for day in horizon]

        for day, (yhat, lower, upper) in list(zip(horizon, predictions, strict=True))[
            :DEMAND_HORIZON_DAYS
        ]:
            rows.append(
                {
                    "product_id": snapshot.product_id,
                    "forecast_type": "demand_qty",
                    "as_of": as_of,
                    "horizon_date": day,
                    "yhat": to_decimal(yhat),
                    "yhat_lower": to_decimal(lower),
                    "yhat_upper": to_decimal(upper),
                    "model_name": model_name,
                    "model_version": model_version,
                    "metadata": meta | {"uncertainty": uncertainty_level(yhat, lower, upper)},
                }
            )

        stockout = _stockout(features, predictions, model_name, model_version)
        if stockout is not None:
            run.stockouts[snapshot.product_id] = stockout
            rows.append(
                {
                    "product_id": snapshot.product_id,
                    "forecast_type": "stockout_date",
                    "as_of": as_of,
                    "horizon_date": as_of + timedelta(days=stockout.days),
                    "yhat": Decimal(stockout.days),
                    "yhat_lower": Decimal(stockout.earliest),
                    "yhat_upper": Decimal(stockout.latest) if stockout.latest is not None else None,
                    "model_name": model_name,
                    "model_version": model_version,
                    "metadata": meta
                    | {
                        "uncertainty": stockout.level,
                        "on_hand": format(stockout.on_hand, "f"),
                        "search_horizon_days": STOCKOUT_HORIZON_DAYS,
                    },
                }
            )

    run.forecast_rows = ForecastRepository(session, ctx).upsert(rows)
    return run


def _stockout(
    features: dict[str, Any],
    predictions: list[tuple[float, float, float]],
    model_name: str,
    model_version: str,
) -> StockoutForecast | None:
    """Premier jour où la demande cumulée prévue atteint le stock du soir de D.

    Les bornes viennent des cumuls des bornes : la demande haute épuise le stock le
    plus tôt, la demande basse le plus tard (ou pas dans l'horizon : `None`).
    """
    if not features.get("stock_tracked") or features.get("on_hand") is None:
        return None
    on_hand = Decimal(str(features["on_hand"]))
    mid = [p[0] for p in predictions]
    daily = to_decimal(sum(mid[:7]) / 7)
    if daily <= 0:
        return None
    if on_hand <= 0:
        return StockoutForecast(0, 0, 0, on_hand, daily, model_name, model_version, "faible")

    def cumulate(values: list[float]) -> list[float]:
        total, out = 0.0, []
        for value in values:
            total += value
            out.append(total)
        return out

    threshold = float(on_hand)
    days = _first_crossing(cumulate(mid), threshold)
    if days is None:
        return None
    earliest = _first_crossing(cumulate([p[2] for p in predictions]), threshold) or days
    latest = _first_crossing(cumulate([p[1] for p in predictions]), threshold)
    spread = (latest if latest is not None else 2 * STOCKOUT_HORIZON_DAYS) - earliest
    level = uncertainty_level(float(days), 0.0, float(spread))
    return StockoutForecast(
        days, earliest, latest, on_hand, daily, model_name, model_version, level
    )
