"""Étape 05 : modèles versionnés, entraînés chaque semaine et par entreprise."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.intelligence.estimators import seasonal
from app.modules.intelligence.estimators.artifacts import ArtifactStore
from app.modules.intelligence.features.builder import MIN_SOLD_DAYS, SOLD_DAYS_WINDOW, is_sufficient
from app.modules.intelligence.pipelines.common import week_version
from app.modules.intelligence.pipelines.features import histories_as_of


@dataclass(frozen=True)
class TrainRun:
    model_name: str
    model_version: str
    path: Path
    fitted: int
    skipped: int


def train(session: Session, ctx: TenantContext, *, as_of: date, store: ArtifactStore) -> TrainRun:
    """Ajuste la régression saisonnière de chaque produit suffisamment documenté.

    Un seul artefact par entreprise et par semaine : l'ensemble des coefficients
    produits ensemble porte une seule version, celle qu'on retrouvera dans
    `forecasts.model_version`. Les produits sous le seuil ne sont pas entraînés — et
    un produit suffisant mais trop peu observable tombera sur la moyenne mobile.
    """
    version = week_version(as_of)
    fitted: dict[str, Any] = {}
    skipped = 0
    for product_id, history in histories_as_of(session, ctx, as_of=as_of).items():
        first = history.first_sale_day
        history_days = (as_of - first).days + 1 if first else 0
        sold_days = sum(1 for value in history.qty[-SOLD_DAYS_WINDOW:] if value > 0)
        if not is_sufficient(history_days, sold_days):
            skipped += 1
            continue
        fit = seasonal.fit_seasonal(history.days, history.floats(), history.censored)
        if fit is None:
            skipped += 1
            continue
        fitted[str(product_id)] = fit.to_json()

    payload = {
        "model_name": seasonal.MODEL_NAME,
        "model_version": version,
        "trained_at": datetime.now(UTC).isoformat(),
        "trained_as_of": as_of.isoformat(),
        "train_window_days": seasonal.TRAIN_WINDOW_DAYS,
        "min_sold_days": MIN_SOLD_DAYS,
        "products": fitted,
    }
    path = store.save(ctx.company_id, seasonal.MODEL_NAME, version, payload)
    return TrainRun(
        model_name=seasonal.MODEL_NAME,
        model_version=version,
        path=path,
        fitted=len(fitted),
        skipped=skipped,
    )
