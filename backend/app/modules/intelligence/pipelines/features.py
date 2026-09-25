"""Étapes 02 à 04 : collecte au point D, préparation, features figées."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.companies import service as companies_service
from app.modules.intelligence.features.builder import (
    HISTORY_WINDOW_DAYS,
    build_features,
    build_labels,
)
from app.modules.intelligence.features.series import ProductHistory, load_histories
from app.modules.intelligence.repository import SnapshotRepository
from app.modules.products import service as products_service

#: Profondeur du rattrapage des labels : au-delà, les jours ne sont plus dans la série.
LABEL_LOOKBACK_DAYS = HISTORY_WINDOW_DAYS - 8


@dataclass(frozen=True)
class FeatureRun:
    as_of: date
    written: int
    already_present: int
    labelled: int


def histories_as_of(
    session: Session, ctx: TenantContext, *, as_of: date
) -> dict[UUID, ProductHistory]:
    """Séries denses de tous les produits actifs, connues au soir de `as_of`."""
    return load_histories(
        session,
        ctx,
        products=products_service.active_summaries(session, ctx),
        as_of=as_of,
        window_days=HISTORY_WINDOW_DAYS,
        timezone=companies_service.get_timezone(session, ctx),
    )


def compute_features(session: Session, ctx: TenantContext, *, as_of: date) -> FeatureRun:
    """Photographie chaque produit actif à `as_of`, **une seule fois** (§ 6.2).

    Un rejeu ne réécrit rien : la photographie de D est ce qui était connu à D, et un
    retour enregistré depuis ne doit pas la modifier. Les labels des photographies
    dont les 7 jours suivants sont désormais connus sont complétés au passage.
    """
    histories = histories_as_of(session, ctx, as_of=as_of)
    repository = SnapshotRepository(session, ctx)

    written = 0
    for product_id, history in histories.items():
        if repository.insert_once(
            product_id=product_id, as_of=as_of, features=build_features(history, as_of)
        ):
            written += 1

    labelled = 0
    for snapshot in repository.without_labels(
        since=as_of - timedelta(days=LABEL_LOOKBACK_DAYS), until=as_of - timedelta(days=7)
    ):
        known = histories.get(snapshot.product_id)
        if known is None:
            continue
        labels = build_labels(known, snapshot.as_of)
        if labels is not None:
            repository.set_labels(snapshot.id, labels)
            labelled += 1

    return FeatureRun(
        as_of=as_of,
        written=written,
        already_present=len(histories) - written,
        labelled=labelled,
    )
