"""API de CoGes Intelligence : lecture seule de résultats déjà calculés.

Chaque élément se qualifie (métrique, valeur, date, modèle, incertitude) ; seul le
statut d'un insight est modifiable ; une ressource d'une autre entreprise est un 404.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.intelligence.estimators.artifacts import ArtifactStore
from tests.conftest import auth_headers, create_user_with_role, login_token
from tests.integration import intelligence_harness as ih
from tests.integration import intelligence_scenario as scenario

pytestmark = pytest.mark.integration

INSIGHTS = "/api/v1/insights"
FORECASTS = "/api/v1/forecasts"
SUMMARY = "/api/v1/intelligence/summary"


@pytest.fixture
def boutique(
    api_client: TestClient,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tmp_path: Path,
) -> scenario.Boutique:
    built = scenario.build(session_factory, "api")
    ih.pipeline(
        analytics_session_factory, built.shop, as_of=built.as_of, store=ArtifactStore(tmp_path)
    )
    return built


@pytest.fixture
def token(api_client: TestClient, boutique: scenario.Boutique) -> str:
    return login_token(api_client, boutique.shop.company)


def test_insights_are_qualified_and_paginated(
    api_client: TestClient, boutique: scenario.Boutique, token: str
) -> None:
    response = api_client.get(f"{INSIGHTS}?page_size=100", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    assert body["total"] == len(body["items"]) >= 3
    for item in body["items"]:
        assert item["metric_name"], item
        assert item["value"] is not None, item
        assert item["computed_at"]
        assert item["status"] == "new"
    kinds = {item["insight_type"] for item in body["items"]}
    assert {"insufficient_history", "stockout_risk", "slow_mover"} <= kinds

    insufficient = [i for i in body["items"] if i["insight_type"] == "insufficient_history"]
    assert all(item["insufficient_data"] is True for item in insufficient)
    stockout = next(i for i in body["items"] if i["insight_type"] == "stockout_risk")
    assert stockout["model_name"] == "seasonal_ols"
    assert stockout["uncertainty"]["level"] in {"faible", "moyenne", "élevée"}


def test_insights_filter_by_type_and_severity(
    api_client: TestClient, boutique: scenario.Boutique, token: str
) -> None:
    by_type = api_client.get(f"{INSIGHTS}?type=slow_mover", headers=auth_headers(token)).json()
    assert by_type["total"] >= 1
    assert {item["insight_type"] for item in by_type["items"]} == {"slow_mover"}

    info = api_client.get(f"{INSIGHTS}?severity=info", headers=auth_headers(token)).json()
    assert {item["severity"] for item in info["items"]} == {"info"}

    paged = api_client.get(f"{INSIGHTS}?page_size=1&page=2", headers=auth_headers(token)).json()
    assert len(paged["items"]) == 1 and paged["page"] == 2


SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def test_insights_are_listed_by_severity_then_newest_first(
    api_client: TestClient,
    boutique: scenario.Boutique,
    token: str,
    analytics_session_factory: sessionmaker[Any],
) -> None:
    """Critique, attention, information ; dans une même sévérité, le plus récent d'abord.

    Le cas construit est celui que l'ancien tri (date seule) aurait mal rangé : une
    information toute récente ne passe pas devant une critique plus ancienne.
    """
    now = dt.datetime.now(dt.UTC)
    planted = {
        "info-recente": ("info", now),
        "critique-ancienne": ("critical", now - dt.timedelta(days=2)),
        "critique-recente": ("critical", now - dt.timedelta(hours=1)),
        "attention": ("warning", now - dt.timedelta(days=1)),
    }
    ctx = TenantContext.bootstrap(boutique.shop.company_id)
    with tenant_transaction(ctx, session_factory=analytics_session_factory) as session:
        for key, (severity, generated_at) in planted.items():
            session.execute(
                text(
                    "INSERT INTO insights (company_id, insight_type, severity, title, "
                    "dedupe_key, generated_at) VALUES (:company, 'debt_overdue', "
                    "CAST(:severity AS insight_severity), :title, :key, :at)"
                ),
                {
                    "company": ctx.company_id,
                    "severity": severity,
                    "title": f"Tri {key}",
                    "key": f"tri:{key}",
                    "at": generated_at,
                },
            )

    response = api_client.get(f"{INSIGHTS}?page_size=100", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    items = response.json()["items"]

    # Toute la liste : sévérité jamais croissante, date décroissante à sévérité égale.
    keys = [
        (
            SEVERITY_RANK[item["severity"]],
            -dt.datetime.fromisoformat(item["computed_at"]).timestamp(),
        )
        for item in items
    ]
    assert keys == sorted(keys)

    ours = [item["title"] for item in items if item["title"].startswith("Tri ")]
    assert ours == [
        "Tri critique-recente",
        "Tri critique-ancienne",
        "Tri attention",
        "Tri info-recente",
    ]


def test_forecasts_carry_date_model_and_interval(
    api_client: TestClient, boutique: scenario.Boutique, token: str
) -> None:
    response = api_client.get(
        f"{FORECASTS}?product_id={boutique.steady}&type=demand_qty",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True and body["insufficient_data"] is False
    assert body["total"] == 14
    first = body["items"][0]
    assert first["metric_name"] == "Quantité vendue prévue"
    assert first["as_of"] == boutique.as_of.isoformat()
    assert first["computed_at"]
    assert first["model_name"] == "seasonal_ols" and first["model_version"]
    assert first["uncertainty"]["lower"] is not None
    assert first["uncertainty"]["upper"] is not None
    assert first["product_name"] == "Riz parfumé 5 kg"


def test_a_product_under_the_threshold_answers_insufficient_data(
    api_client: TestClient, boutique: scenario.Boutique, token: str
) -> None:
    body = api_client.get(
        f"{FORECASTS}?product_id={boutique.rare}", headers=auth_headers(token)
    ).json()
    assert body["items"] == []
    assert body["insufficient_data"] is True


def test_summary_counts_what_is_persisted(
    api_client: TestClient, boutique: scenario.Boutique, token: str
) -> None:
    body = api_client.get(SUMMARY, headers=auth_headers(token)).json()
    assert body["enabled"] is True
    assert body["last_as_of"] == boutique.as_of.isoformat()
    assert body["computed_at"]
    assert body["forecast_products"] == 2  # régulier et dormant ; le rare est sous le seuil
    assert body["insufficient_data_products"] == 1
    assert body["insights_by_type"]["insufficient_history"] == 1
    assert sum(body["insights_by_severity"].values()) == sum(body["insights_by_type"].values())


def test_only_the_status_of_an_insight_changes(
    api_client: TestClient, boutique: scenario.Boutique, token: str
) -> None:
    insight = api_client.get(INSIGHTS, headers=auth_headers(token)).json()["items"][0]
    url = f"{INSIGHTS}/{insight['id']}"

    read = api_client.patch(url, json={"status": "read"}, headers=auth_headers(token))
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "read" and read.json()["read_at"]

    other_column = api_client.patch(
        url, json={"status": "read", "title": "Autre"}, headers=auth_headers(token)
    )
    assert other_column.status_code == 422
    back_to_new = api_client.patch(url, json={"status": "new"}, headers=auth_headers(token))
    assert back_to_new.status_code == 422

    resolved = api_client.patch(url, json={"status": "resolved"}, headers=auth_headers(token))
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"]
    closed = api_client.patch(url, json={"status": "read"}, headers=auth_headers(token))
    assert closed.status_code == 409
    assert closed.json()["error"]["code"] == "insight_closed"

    # Résolu, il sort de la liste par défaut, et se retrouve par son statut.
    live_ids = {
        i["id"] for i in api_client.get(INSIGHTS, headers=auth_headers(token)).json()["items"]
    }
    assert insight["id"] not in live_ids
    resolved_list = api_client.get(f"{INSIGHTS}?status=resolved", headers=auth_headers(token))
    assert insight["id"] in {i["id"] for i in resolved_list.json()["items"]}


def test_an_insight_of_another_company_is_a_404(
    api_client: TestClient, boutique: scenario.Boutique, token: str, beta_token: str
) -> None:
    insight = api_client.get(INSIGHTS, headers=auth_headers(token)).json()["items"][0]
    response = api_client.patch(
        f"{INSIGHTS}/{insight['id']}", json={"status": "read"}, headers=auth_headers(beta_token)
    )
    assert response.status_code == 404
    unknown = api_client.patch(
        f"{INSIGHTS}/{uuid4()}", json={"status": "read"}, headers=auth_headers(token)
    )
    assert unknown.status_code == 404
    # Et rien ne fuit par la lecture : beta ne voit pas les prévisions de la boutique.
    foreign = api_client.get(
        f"{FORECASTS}?product_id={boutique.steady}", headers=auth_headers(beta_token)
    ).json()
    assert foreign["items"] == []


def test_a_salesperson_cannot_read_insights(
    api_client: TestClient, boutique: scenario.Boutique, token: str
) -> None:
    seller = create_user_with_role(
        api_client,
        token,
        boutique.shop.company,
        role="vendeur",
        email=f"vendeur-{uuid4().hex[:8]}@boutique.example.com",
    )
    for url in (INSIGHTS, FORECASTS, SUMMARY):
        assert api_client.get(url, headers=auth_headers(seller)).status_code == 403


def test_future_potential_is_now_served_from_forecasts(
    api_client: TestClient, boutique: scenario.Boutique, token: str
) -> None:
    """Métrique 8 : datée, modèle et intervalle, classée sur **sa** valeur seulement."""
    day = boutique.as_of.isoformat()
    body = api_client.get(
        f"/api/v1/analytics/products?metric=future_potential&from={day}&to={day}",
        headers=auth_headers(token),
    ).json()
    assert body["metric_label"] == "Potentiel futur estimé"
    assert body["unavailable_reason"] is None
    assert body["computed_at"] and body["forecast_as_of"] == day
    assert body["horizon_days"] == 14
    ids = [row["product_id"] for row in body["items"]]
    assert ids[0] == str(boutique.steady)
    assert str(boutique.rare) not in ids
    assert all(row["model_name"] and row["lower"] is not None for row in body["items"])
