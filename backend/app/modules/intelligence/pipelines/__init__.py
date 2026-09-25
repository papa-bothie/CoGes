"""Pipeline CoGes Intelligence (Diagramme 7, étapes 02 à 08).

Points d'entrée des tâches du worker et de la commande `run-intelligence`. Chaque
fonction travaille sur **une** entreprise, dans la transaction que l'appelant a
ouverte avec son contexte tenant, sous `coges_analytics`. Aucune n'est appelée par
l'API : ce paquet importe numpy, pandas et statsmodels, que l'image API n'a pas.

Drapeau coupé (`settings.intelligence_enabled = false`) ⇒ rien n'est calculé ni écrit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.companies import service as companies_service
from app.modules.intelligence.estimators.artifacts import ArtifactStore
from app.modules.intelligence.pipelines.features import FeatureRun, compute_features
from app.modules.intelligence.pipelines.infer import InferRun, infer
from app.modules.intelligence.pipelines.insights import InsightRun, build_drafts, emit
from app.modules.intelligence.pipelines.train import TrainRun, train
from app.modules.intelligence.repository import SnapshotRepository


@dataclass(frozen=True)
class InferenceResult:
    inferred: InferRun
    insights: InsightRun


def run_features(session: Session, ctx: TenantContext, *, as_of: date) -> FeatureRun | None:
    """Étapes 02 à 04. `None` si l'Intelligence est coupée pour l'entreprise."""
    if not companies_service.is_intelligence_enabled(session, ctx):
        return None
    return compute_features(session, ctx, as_of=as_of)


def run_training(
    session: Session, ctx: TenantContext, *, as_of: date, store: ArtifactStore
) -> TrainRun | None:
    """Étape 05, hebdomadaire."""
    if not companies_service.is_intelligence_enabled(session, ctx):
        return None
    return train(session, ctx, as_of=as_of, store=store)


def run_inference(
    session: Session,
    ctx: TenantContext,
    *,
    as_of: date,
    store: ArtifactStore,
    now: datetime | None = None,
) -> InferenceResult | None:
    """Étapes 06 et 07. Photographie `as_of` d'abord si elle manque encore."""
    if not companies_service.is_intelligence_enabled(session, ctx):
        return None
    repository = SnapshotRepository(session, ctx)
    snapshots = list(repository.for_as_of(as_of))
    if not snapshots:
        compute_features(session, ctx, as_of=as_of)
        snapshots = list(repository.for_as_of(as_of))
    inferred = infer(session, ctx, as_of=as_of, snapshots=snapshots, store=store)
    drafts = build_drafts(session, ctx, as_of=as_of, snapshots=snapshots, inferred=inferred)
    insights = emit(session, ctx, as_of=as_of, drafts=drafts, now=now or datetime.now(UTC))
    return InferenceResult(inferred=inferred, insights=insights)


__all__ = [
    "FeatureRun",
    "InferenceResult",
    "TrainRun",
    "run_features",
    "run_inference",
    "run_training",
]
