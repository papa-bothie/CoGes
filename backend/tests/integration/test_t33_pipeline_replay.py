"""T33 — rejouer le pipeline sur le même `as_of` met à jour, sans doublon.

Attaque la base directement : on compte les lignes de `forecasts` et d'`insights`
avant et après un rejeu, et l'on vérifie que ce sont **les mêmes lignes**, mises à
jour — pas des copies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker

from app.modules.intelligence.estimators.artifacts import ArtifactStore
from tests.integration import intelligence_harness as ih
from tests.integration import intelligence_scenario as scenario

pytestmark = pytest.mark.integration

FORECASTS = """
    SELECT id, forecast_type, product_id, horizon_date, yhat, generated_at
      FROM forecasts ORDER BY forecast_type, product_id, horizon_date
"""
INSIGHTS = "SELECT id, dedupe_key, generated_at FROM insights ORDER BY dedupe_key"


def test_t33_replaying_the_same_as_of_updates_instead_of_duplicating(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tmp_path: Path,
) -> None:
    boutique = scenario.build(session_factory, "t33")
    store = ArtifactStore(tmp_path)

    ih.pipeline(analytics_session_factory, boutique.shop, as_of=boutique.as_of, store=store)
    first_forecasts = ih.rows(analytics_session_factory, boutique.shop, FORECASTS)
    first_insights = ih.rows(analytics_session_factory, boutique.shop, INSIGHTS)
    assert first_forecasts, "le scénario doit produire des prévisions"
    assert first_insights, "le scénario doit produire des insights"

    ih.pipeline(analytics_session_factory, boutique.shop, as_of=boutique.as_of, store=store)
    second_forecasts = ih.rows(analytics_session_factory, boutique.shop, FORECASTS)
    second_insights = ih.rows(analytics_session_factory, boutique.shop, INSIGHTS)

    # forecasts : mêmes lignes (mêmes id), mêmes valeurs, horodatage de production avancé.
    assert [r.id for r in second_forecasts] == [r.id for r in first_forecasts]
    assert [r.yhat for r in second_forecasts] == [r.yhat for r in first_forecasts]
    assert all(
        after.generated_at > before.generated_at
        for before, after in zip(first_forecasts, second_forecasts, strict=True)
    )
    # insights : même dedupe_key ⇒ même ligne, mise à jour.
    assert [r.id for r in second_insights] == [r.id for r in first_insights]
    assert all(
        after.generated_at > before.generated_at
        for before, after in zip(first_insights, second_insights, strict=True)
    )


def test_t33_feature_snapshots_are_written_once(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> None:
    """La photographie d'un `as_of` n'est jamais réécrite : le rejeu n'écrit rien."""
    boutique = scenario.build(session_factory, "t33-snap")

    first = ih.features(analytics_session_factory, boutique.shop, as_of=boutique.as_of)
    second = ih.features(analytics_session_factory, boutique.shop, as_of=boutique.as_of)

    assert first is not None and second is not None
    assert first.written == 3
    assert second.written == 0 and second.already_present == 3
    count = ih.rows(
        analytics_session_factory, boutique.shop, "SELECT count(*) AS n FROM ml_feature_snapshots"
    )
    assert count[0].n == 3
