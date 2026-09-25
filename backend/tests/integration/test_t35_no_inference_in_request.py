"""T35 — les écrans de prévision ne lisent que `forecasts` et `insights`, par index.

Trace SQL réelle des requêtes émises pendant les appels HTTP, sur le moteur de
`coges_app` : aucune lecture de `ml_feature_snapshots` ni des tables transactionnelles,
donc aucun calcul. Chaque requête sur `forecasts`/`insights` est ensuite expliquée
par PostgreSQL, balayage séquentiel interdit : elle doit avoir un index à emprunter.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.modules.intelligence.estimators.artifacts import ArtifactStore
from tests.conftest import auth_headers, login_token
from tests.integration import intelligence_harness as ih
from tests.integration import intelligence_scenario as scenario

pytestmark = pytest.mark.integration

#: Ce que l'écran de prévision n'a jamais le droit de toucher : les features, et tout
#: ce dont un calcul aurait besoin.
FORBIDDEN = (
    "ml_feature_snapshots",
    "daily_sales_facts",
    "sales",
    "sale_items",
    "sale_returns",
    "sale_return_items",
    "inventory_movements",
    "product_stock",
    "products",
    "payments",
    "debts",
)


@pytest.fixture
def captured(app_engine: Engine) -> Iterator[list[tuple[str, Any]]]:
    statements: list[tuple[str, Any]] = []

    def _capture(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        statements.append((statement, parameters))

    event.listen(app_engine, "before_cursor_execute", _capture)
    try:
        yield statements
    finally:
        event.remove(app_engine, "before_cursor_execute", _capture)


def _tables(statement: str) -> set[str]:
    return set(re.findall(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([a-z_]+)", statement, re.IGNORECASE))


def test_t35_forecast_screens_read_only_results_by_index(
    api_client: TestClient,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    app_engine: Engine,
    tmp_path: Path,
    captured: list[tuple[str, Any]],
) -> None:
    boutique = scenario.build(session_factory, "t35")
    ih.pipeline(
        analytics_session_factory,
        boutique.shop,
        as_of=boutique.as_of,
        store=ArtifactStore(tmp_path),
    )
    token = login_token(api_client, boutique.shop.company)
    captured.clear()

    for url in (
        "/api/v1/insights",
        f"/api/v1/forecasts?product_id={boutique.steady}&type=demand_qty",
        f"/api/v1/forecasts?product_id={boutique.rare}",
        "/api/v1/intelligence/summary",
    ):
        assert api_client.get(url, headers=auth_headers(token)).status_code == 200

    touched = set().union(*(_tables(statement) for statement, _ in captured))
    assert not touched & set(FORBIDDEN), f"lecture interdite : {touched & set(FORBIDDEN)}"
    assert {"forecasts", "insights"} <= touched

    results = [
        (statement, params)
        for statement, params in captured
        if _tables(statement) & {"forecasts", "insights"}
    ]
    assert results
    with app_engine.connect() as connection, connection.begin():
        connection.exec_driver_sql(
            "SELECT set_config('app.company_id', %(cid)s, true)",
            {"cid": str(boutique.shop.company_id)},
        )
        connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
        for statement, params in results:
            plan = "\n".join(
                row[0] for row in connection.exec_driver_sql(f"EXPLAIN {statement}", params)
            )
            assert "Seq Scan on forecasts" not in plan, plan
            assert "Seq Scan on insights" not in plan, plan
            assert "Index" in plan, plan
