"""Ce que le pipeline produit sur la boutique type, lu directement en base.

Chaque résultat se qualifie : métrique nommée, valeur, modèle et version, incertitude
— ou « données insuffisantes », jamais une valeur inventée (décisions 12 et 13).
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


@pytest.fixture
def produced(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tmp_path: Path,
) -> scenario.Boutique:
    boutique = scenario.build(session_factory, "pipeline")
    ih.pipeline(
        analytics_session_factory,
        boutique.shop,
        as_of=boutique.as_of,
        store=ArtifactStore(tmp_path),
    )
    return boutique


def _forecasts(factory: sessionmaker[Any], boutique: scenario.Boutique, product: Any) -> list[Any]:
    return ih.rows(
        factory,
        boutique.shop,
        "SELECT * FROM forecasts WHERE product_id = :p ORDER BY forecast_type, horizon_date",
        p=product,
    )


def _insights(factory: sessionmaker[Any], boutique: scenario.Boutique, kind: str) -> list[Any]:
    return ih.rows(
        factory,
        boutique.shop,
        "SELECT * FROM insights WHERE insight_type = CAST(:k AS insight_type)",
        k=kind,
    )


def test_a_product_under_the_threshold_gets_no_forecast_and_an_explicit_insight(
    produced: scenario.Boutique, analytics_session_factory: sessionmaker[Any]
) -> None:
    """Deux ventes : aucune prévision, et un insight « données insuffisantes »."""
    assert _forecasts(analytics_session_factory, produced, produced.rare) == []
    insights = _insights(analytics_session_factory, produced, "insufficient_history")
    rare = [row for row in insights if row.entity_id == produced.rare]
    assert len(rare) == 1
    assert rare[0].severity == "info"
    assert rare[0].title.startswith("Données insuffisantes")
    assert rare[0].evidence["metric_name"] == "Historique de ventes"
    assert rare[0].evidence["thresholds"] == {
        "min_history_days": 28,
        "min_sold_days": 5,
        "sold_days_window": 60,
    }
    assert rare[0].evidence["insufficient_data"] is True


def test_a_regular_product_gets_a_dated_versioned_interval_forecast(
    produced: scenario.Boutique, analytics_session_factory: sessionmaker[Any]
) -> None:
    rows = _forecasts(analytics_session_factory, produced, produced.steady)
    demand = [row for row in rows if row.forecast_type == "demand_qty"]
    assert len(demand) == 14
    assert {row.as_of for row in demand} == {produced.as_of}
    for row in demand:
        assert row.model_name == "seasonal_ols"
        assert row.model_version.startswith(str(produced.as_of.isocalendar().year))
        assert row.yhat_lower is not None and row.yhat_upper is not None
        assert row.yhat_lower <= row.yhat <= row.yhat_upper
        assert row.metadata["uncertainty"] in {"faible", "moyenne", "élevée"}
        assert row.metadata["product_name"] == "Riz parfumé 5 kg"
        assert row.metadata["artifact_path"].endswith(f"{row.model_version}.json")


def test_low_stock_on_a_regular_product_raises_a_stockout_risk(
    produced: scenario.Boutique, analytics_session_factory: sessionmaker[Any]
) -> None:
    """20 unités pour ~3,6 par jour : rupture sous la semaine, prévision et insight."""
    stockout = [
        row
        for row in _forecasts(analytics_session_factory, produced, produced.steady)
        if row.forecast_type == "stockout_date"
    ]
    assert len(stockout) == 1
    days = int(stockout[0].yhat)
    assert 1 <= days <= 7
    assert (stockout[0].horizon_date - produced.as_of).days == days

    risks = [
        row
        for row in _insights(analytics_session_factory, produced, "stockout_risk")
        if row.entity_id == produced.steady
    ]
    assert len(risks) == 1
    assert risks[0].evidence["metric_name"] == "Jours avant rupture prévue"
    assert risks[0].evidence["value"] == str(days)
    assert risks[0].model_name == "seasonal_ols"
    assert risks[0].dedupe_key.startswith(f"stockout_risk:{produced.steady}:")


def test_a_dormant_stock_is_named_a_slow_mover_on_a_named_metric(
    produced: scenario.Boutique, analytics_session_factory: sessionmaker[Any]
) -> None:
    slow = [
        row
        for row in _insights(analytics_session_factory, produced, "slow_mover")
        if row.entity_id == produced.dormant
    ]
    assert len(slow) == 1
    evidence = slow[0].evidence
    assert evidence["metric_name"] == "Vélocité des ventes"
    assert evidence["abc_metric"] == "Chiffre d'affaires généré sur 28 jours"
    assert evidence["abc_class"] == "C"


def test_a_critical_insight_notifies_the_people_who_can_read_insights(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tmp_path: Path,
) -> None:
    """Rupture sous trois jours ⇒ insight critique ⇒ une notification, une seule fois."""
    shop = ih.new_shop("critical")
    as_of = ih.today()
    with ih.write(session_factory, shop) as session:
        product = ih.add_product(session, shop, "Huile 1 L")
        ih.sell_daily(session, shop, product, until=as_of, days=60, pattern=(5,) * 7)
        ih.stock_in(session, shop, product, "6")
    store = ArtifactStore(tmp_path)

    ih.pipeline(analytics_session_factory, shop, as_of=as_of, store=store)
    ih.pipeline(analytics_session_factory, shop, as_of=as_of, store=store)

    critical = ih.rows(
        analytics_session_factory,
        shop,
        "SELECT id FROM insights WHERE severity = 'critical' AND insight_type = 'stockout_risk'",
    )
    assert len(critical) == 1
    notifications = ih.rows(
        session_factory,
        shop,
        "SELECT user_id, data FROM notifications WHERE type = 'insight_critical'",
    )
    assert len(notifications) == 1, "le rejeu ne réveille personne une seconde fois"
    assert notifications[0].user_id == shop.user_id
    assert notifications[0].data["insight_id"] == str(critical[0].id)
