"""Désactivation : Intelligence coupée ⇒ aucun calcul, API `enabled: false`, et CoGes
continue de fonctionner (Diagramme 7, « Désactivation »)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.modules.intelligence.estimators.artifacts import ArtifactStore
from tests.conftest import auth_headers, login_token
from tests.integration import intelligence_harness as ih
from tests.integration import intelligence_scenario as scenario

pytestmark = pytest.mark.integration


def test_a_disabled_company_computes_nothing_and_serves_enabled_false(
    api_client: TestClient,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tmp_path: Path,
) -> None:
    boutique = scenario.build(session_factory, "off")
    ih.set_intelligence(session_factory, boutique.shop, enabled=False)

    result = ih.pipeline(
        analytics_session_factory,
        boutique.shop,
        as_of=boutique.as_of,
        store=ArtifactStore(tmp_path),
    )
    assert result is None
    for table in ("ml_feature_snapshots", "forecasts", "insights"):
        count = ih.rows(
            analytics_session_factory, boutique.shop, f"SELECT count(*) AS n FROM {table}"
        )
        assert count[0].n == 0, f"{table} écrite alors que l'Intelligence est coupée"
    assert not any(tmp_path.iterdir()), "aucun artefact ne doit être entraîné"

    token = login_token(api_client, boutique.shop.company)
    headers = auth_headers(token)
    for url in ("/api/v1/insights", "/api/v1/forecasts", "/api/v1/intelligence/summary"):
        response = api_client.get(url, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["enabled"] is False

    day = boutique.as_of.isoformat()
    ranking = api_client.get(
        f"/api/v1/analytics/products?metric=future_potential&from={day}&to={day}",
        headers=headers,
    ).json()
    assert ranking["items"] == []
    assert "désactivée" in ranking["unavailable_reason"]

    # Le reste de CoGes ne remarque rien.
    assert api_client.get("/api/v1/dashboard", headers=headers).status_code == 200
    assert (
        api_client.get(
            f"/api/v1/analytics/products?metric=revenue&from={day}&to={day}", headers=headers
        ).status_code
        == 200
    )
    assert api_client.get("/api/v1/products", headers=headers).status_code == 200


def test_switching_it_back_on_resumes_the_pipeline(
    api_client: TestClient,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tmp_path: Path,
) -> None:
    boutique = scenario.build(session_factory, "on-again")
    ih.set_intelligence(session_factory, boutique.shop, enabled=False)
    ih.set_intelligence(session_factory, boutique.shop, enabled=True)

    result = ih.pipeline(
        analytics_session_factory,
        boutique.shop,
        as_of=boutique.as_of,
        store=ArtifactStore(tmp_path),
    )
    assert result is not None and result.inferred.forecast_rows > 0
