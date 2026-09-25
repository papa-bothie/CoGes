"""T1, T2 et T36 étendus aux tables de CoGes Intelligence (révision 0011).

`ml_feature_snapshots`, `forecasts` et `insights` sont écrites par `coges_analytics`
et, pour `ml_feature_snapshots`, **illisibles** par `coges_app` : les tests croisés
génériques de `test_t01_t05_cross_tenant.py`, qui tournent sous `coges_app`, ne
peuvent donc pas les couvrir. Ils sont repris ici sous le rôle qui les écrit, et
sous `coges_app` pour les deux tables que l'API lit.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import tenant_transaction
from app.modules.intelligence.estimators.artifacts import ArtifactStore
from tests.integration import intelligence_harness as ih
from tests.integration import intelligence_scenario as scenario
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.tenancy

APP_ROLE = "coges_app"
ANALYTICS_ROLE = "coges_analytics"
TABLES = ("ml_feature_snapshots", "forecasts", "insights")
AS_OF = dt.date(2026, 9, 1)


def _seed(factory: sessionmaker[Any], tenant: Tenant) -> None:
    with tenant_transaction(tenant.ctx, session_factory=factory) as session:
        session.execute(
            text(
                "INSERT INTO ml_feature_snapshots (company_id, product_id, as_of, features) "
                "VALUES (:c, :p, :d, '{}'::jsonb) ON CONFLICT DO NOTHING"
            ),
            {"c": tenant.company_id, "p": tenant.product_id, "d": AS_OF},
        )
        session.execute(
            text(
                "INSERT INTO forecasts (company_id, product_id, forecast_type, as_of, "
                " horizon_date, yhat, model_name, model_version) "
                "VALUES (:c, :p, 'demand_qty', :d, :d, 1, 'harness', 'isolation') "
                "ON CONFLICT DO NOTHING"
            ),
            {"c": tenant.company_id, "p": tenant.product_id, "d": AS_OF},
        )
        session.execute(
            text(
                "INSERT INTO insights (company_id, insight_type, severity, title, dedupe_key, "
                " entity_table, entity_id) "
                "VALUES (:c, 'slow_mover', 'info', 'Écoulement lent', :k, 'products', :p)"
            ),
            {"c": tenant.company_id, "p": tenant.product_id, "k": f"harness:{uuid4()}"},
        )


@pytest.fixture(scope="module")
def seeded(
    analytics_session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> tuple[Tenant, Tenant]:
    _seed(analytics_session_factory, tenant_a)
    _seed(analytics_session_factory, tenant_b)
    return tenant_a, tenant_b


def _visible(factory: sessionmaker[Any], reader: Tenant, owner: Tenant, table: str) -> Any:
    with tenant_transaction(reader.ctx, session_factory=factory) as session:
        foreign = session.execute(
            text(f"SELECT count(*) FROM {table} WHERE company_id = :c"), {"c": owner.company_id}
        ).scalar_one()
        own = session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    return foreign, own


@pytest.mark.parametrize("table", TABLES)
def test_t01_intelligence_tables_are_isolated_for_the_pipeline(
    analytics_session_factory: sessionmaker[Any], seeded: tuple[Tenant, Tenant], table: str
) -> None:
    tenant_a, tenant_b = seeded
    for reader, owner in ((tenant_a, tenant_b), (tenant_b, tenant_a)):
        foreign, own = _visible(analytics_session_factory, reader, owner, table)
        assert foreign == 0, f"fuite de lecture sur {table}"
        assert own >= 1, f"{table} : le lecteur ne voit plus ses propres lignes"


@pytest.mark.parametrize("table", ("forecasts", "insights"))
def test_t01_intelligence_results_are_isolated_for_the_api(
    session_factory: sessionmaker[Any], seeded: tuple[Tenant, Tenant], table: str
) -> None:
    tenant_a, tenant_b = seeded
    foreign, own = _visible(session_factory, tenant_a, tenant_b, table)
    assert foreign == 0 and own >= 1


def test_t02_the_pipeline_cannot_write_for_another_company(
    analytics_session_factory: sessionmaker[Any], seeded: tuple[Tenant, Tenant]
) -> None:
    tenant_a, tenant_b = seeded
    with (
        pytest.raises(DBAPIError, match="row-level security"),
        tenant_transaction(tenant_a.ctx, session_factory=analytics_session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO insights (company_id, insight_type, severity, title, dedupe_key) "
                "VALUES (:c, 'slow_mover', 'info', 'Intrusion', :k)"
            ),
            {"c": tenant_b.company_id, "k": f"intrusion:{uuid4()}"},
        )


def test_t35_the_application_cannot_read_feature_snapshots(
    session_factory: sessionmaker[Any], seeded: tuple[Tenant, Tenant]
) -> None:
    """Structurel : même un bug de l'API ne pourrait pas lire les features."""
    tenant_a, _ = seeded
    with (
        pytest.raises(ProgrammingError, match="permission denied"),
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(text("SELECT count(*) FROM ml_feature_snapshots")).scalar_one()


def test_the_application_never_writes_results(
    session_factory: sessionmaker[Any], seeded: tuple[Tenant, Tenant]
) -> None:
    tenant_a, _ = seeded
    with (
        pytest.raises(ProgrammingError, match="permission denied"),
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO forecasts (company_id, forecast_type, as_of, horizon_date, yhat, "
                " model_name, model_version) "
                "VALUES (:c, 'revenue', :d, :d, 1, 'api', 'forged')"
            ),
            {"c": tenant_a.company_id, "d": AS_OF},
        )
    with (
        pytest.raises(ProgrammingError, match="permission denied"),
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(text("UPDATE insights SET title = 'Réécrit'"))


def _column_privilege(engine: Engine, role: str, table: str, column: str, privilege: str) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT has_column_privilege(:role, :table, :column, :privilege)"),
                {"role": role, "table": table, "column": column, "privilege": privilege},
            ).scalar_one()
        )


def _table_privilege(engine: Engine, role: str, table: str, privilege: str) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT has_table_privilege(:role, :table, :privilege)"),
                {"role": role, "table": table, "privilege": privilege},
            ).scalar_one()
        )


def test_t36_intelligence_privileges_are_named(app_engine: Engine) -> None:
    """Les phrases de l'Architecture, écrites en GRANT (ADR 0036)."""
    # « Jamais lue par l'application. »
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert not _table_privilege(app_engine, APP_ROLE, "ml_feature_snapshots", privilege)
    # « Écrite exclusivement par le processus analytique. »
    assert _table_privilege(app_engine, APP_ROLE, "forecasts", "SELECT")
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert not _table_privilege(app_engine, APP_ROLE, "forecasts", privilege)
    # « status : seule colonne modifiable par l'application » (+ ses deux dates).
    assert not _table_privilege(app_engine, APP_ROLE, "insights", "INSERT")
    for column in ("status", "read_at", "resolved_at"):
        assert _column_privilege(app_engine, APP_ROLE, "insights", column, "UPDATE")
    for column in ("title", "body", "evidence", "severity", "dedupe_key", "company_id"):
        assert not _column_privilege(app_engine, APP_ROLE, "insights", column, "UPDATE")

    # Le pipeline : features écrites une fois, seuls les labels se complètent.
    assert _table_privilege(app_engine, ANALYTICS_ROLE, "ml_feature_snapshots", "INSERT")
    assert _column_privilege(app_engine, ANALYTICS_ROLE, "ml_feature_snapshots", "labels", "UPDATE")
    for column in ("features", "as_of", "product_id"):
        assert not _column_privilege(
            app_engine, ANALYTICS_ROLE, "ml_feature_snapshots", column, "UPDATE"
        )
    for table in TABLES:
        assert not _table_privilege(app_engine, ANALYTICS_ROLE, table, "DELETE")
    assert _table_privilege(app_engine, ANALYTICS_ROLE, "notifications", "INSERT")


def test_the_pipeline_of_one_company_writes_nothing_elsewhere(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tmp_path: Any,
) -> None:
    """Une entreprise à la fois, avec son contexte : le voisin ne reçoit rien."""
    boutique = scenario.build(session_factory, "iso-run")
    neighbour = ih.new_shop("iso-neighbour")
    ih.pipeline(
        analytics_session_factory,
        boutique.shop,
        as_of=boutique.as_of,
        store=ArtifactStore(tmp_path),
    )

    for table in TABLES:
        mine = ih.rows(
            analytics_session_factory, boutique.shop, f"SELECT count(*) AS n FROM {table}"
        )
        theirs = ih.rows(analytics_session_factory, neighbour, f"SELECT count(*) AS n FROM {table}")
        assert mine[0].n > 0, table
        assert theirs[0].n == 0, f"{table} : le pipeline a écrit chez le voisin"
