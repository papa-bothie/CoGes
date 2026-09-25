"""Socle commun aux trois tâches de CoGes Intelligence.

Elles tournent sous **`coges_analytics`** : le seul rôle qui peut écrire
`ml_feature_snapshots`, `forecasts` et `insights` (révision 0011), sans pouvoir y
supprimer quoi que ce soit. Une entreprise à la fois, avec son contexte tenant, dans
sa propre transaction : une entreprise en échec n'arrête pas les autres.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_analytics_session_factory
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.intelligence.estimators.artifacts import ArtifactStore
from app.modules.intelligence.pipelines.common import yesterday


def artifact_store() -> ArtifactStore:
    return ArtifactStore(get_settings().ml_artifacts_dir)


def run_for_company[T](
    company_id: str, as_of: str | None, step: Callable[[Session, TenantContext, date], T]
) -> T:
    """Ouvre la transaction de l'entreprise, fixe `as_of` (la veille locale par défaut)."""
    ctx = TenantContext.bootstrap(UUID(company_id))
    with tenant_transaction(ctx, session_factory=get_analytics_session_factory()) as session:
        day = date.fromisoformat(as_of) if as_of else yesterday(session, ctx)
        return step(session, ctx, day)
