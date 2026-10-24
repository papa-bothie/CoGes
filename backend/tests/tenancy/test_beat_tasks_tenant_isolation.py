"""Tâches de fond : une entreprise par tâche, une panne n'arrête pas les autres (lot C, C4).

Complète `test_worker_tenant_isolation.py` pour **toutes** les tâches de `BEAT_SCHEDULE` :

* registre : chaque tâche planifiée est un éventail (une sous-tâche par entreprise,
  nommée ici) ou une tâche de plate-forme (raison écrite) ; une tâche non classée fait
  échouer la CI ;
* chaque sous-tâche lancée pour A ne change **rien** chez B — empreinte de toutes les
  tables de B, ML compris, lue par le propriétaire sous le contexte de B ;
* relancée deux fois de suite pour A, elle laisse les mêmes comptages (pas de doublon) ;
* une entreprise en échec n'empêche ni les suivantes ni la trace `failed` dans `job_runs`,
  avec son `company_id`.

Le relais (événement empoisonné mis de côté après dix essais, at-least-once avec
consommateurs idempotents) est prouvé par T40 (`test_t40_outbox_relay.py`) et
`test_worker_tenant_isolation.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.workers import beat
from app.workers.tasks import (
    analytics,
    exports,
    ml_features,
    ml_infer,
    ml_train,
    notifications,
    platform,
    reconcile,
)
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    login_token,
    write_headers,
)

pytestmark = [pytest.mark.tenancy, pytest.mark.usefixtures("workers_bound_to_test_database")]

#: Éventail → sous-tâche lancée pour une seule entreprise.
FAN_OUT: dict[str, Callable[[str], Any]] = {
    beat.REBUILD_STOCK: reconcile.rebuild_stock,
    beat.REBUILD_RECENT_FACTS: lambda company: analytics.rebuild_recent_facts(company, 7),
    beat.CHECK_REVENUE: reconcile.check_revenue,
    beat.SCAN_DUE_DEBTS: notifications.scan_due_debts,
    beat.ML_FEATURES: ml_features.compute,
    beat.ML_TRAIN: ml_train.train,
    beat.ML_INFER: ml_infer.infer,
    beat.SWEEP_EXPORTS: exports.sweep,
    # Fin des essais (ADR 0091) : la tâche de nuit décide sous le rôle de la plateforme,
    # puis prévient chaque entreprise dans son propre contexte.
    beat.SUBSCRIPTIONS_DAILY: lambda company: platform.trial_notice(
        company, 7, (datetime.now(UTC) + timedelta(days=7)).isoformat()
    ),
}
#: Tâches de plate-forme : aucune donnée d'une entreprise lue ou écrite en son nom.
PLATFORM: dict[str, str] = {
    beat.ENSURE_PARTITIONS: "crée des partitions d'audit, communes à toutes les entreprises",
    beat.PURGE_IDEMPOTENCY: "purge les clés échues par une fonction privilégiée, sans les lire",
    beat.PURGE_JOB_RUNS: "purge le journal des tâches (plate-forme, ADR 0077)",
    beat.BEAT_TICK: "écrit l'heure du tic dans Redis, aucune donnée d'entreprise",
    beat.SUPPORT_SESSIONS_CLOSE: (
        "ferme les accès support échus sous le rôle de la plateforme (ADR 0092), "
        "sans rien lire d'une entreprise"
    ),
}

_TABLES = text(
    """
    SELECT c.relname FROM pg_class c
    JOIN pg_attribute a
      ON a.attrelid = c.oid AND a.attname = 'company_id' AND NOT a.attisdropped
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
      AND NOT c.relispartition
    ORDER BY c.relname
    """
)


def owner_snapshot(owner_engine: Engine, company_id: UUID) -> dict[str, tuple[int, str]]:
    """(lignes, empreinte) de chaque table de l'entreprise, ML et journaux compris.

    Le propriétaire ne franchit pas la RLS (FORCE) : il lit sous le contexte de
    l'entreprise, comme elle, mais sans les restrictions de privilèges des rôles
    d'exécution.
    """
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(company_id)}
        )
        tables = list(connection.execute(_TABLES).scalars())
        state: dict[str, tuple[int, str]] = {}
        for table in tables:
            row = connection.execute(
                text(
                    f"SELECT count(*), md5(coalesce(string_agg(x::text, '|' "
                    f"ORDER BY x::text), '')) FROM {table} x"
                )
            ).one()
            state[table] = (int(row[0]), str(row[1]))
        return state


def _shop(client: TestClient, tag: str) -> DemoCompany:
    company = _create_demo_company(f"{tag}-{uuid4().hex[:6]}")
    token = login_token(client, company)

    def post(path: str, body: Any) -> dict[str, Any]:
        response = client.post(path, headers=write_headers(token), json=body)
        assert response.status_code in (200, 201), f"{path} : {response.text}"
        return dict(response.json())

    product = post("/api/v1/products", {"name": f"Article {tag}", "unit_price": "1000"})
    post(
        "/api/v1/inventory/movements",
        {"product_id": product["id"], "type": "initial", "qty_delta": "30", "unit_cost": "600"},
    )
    customer = post("/api/v1/customers", {"name": f"Client {tag}"})
    sale = post("/api/v1/sales", {"customer_id": customer["id"]})
    post(f"/api/v1/sales/{sale['id']}/items", {"product_id": product["id"], "qty": "2"})
    post(
        f"/api/v1/sales/{sale['id']}/confirm",
        {"paid_amount": "0", "method": "cash", "due_date": "2026-01-01"},
    )
    return company


@pytest.fixture(scope="module")
def pair(app_bound_to_test_database: None) -> tuple[DemoCompany, DemoCompany]:
    with TestClient(app_module(), base_url=TEST_BASE_URL) as client:
        return _shop(client, "fond-a"), _shop(client, "fond-b")


def app_module() -> Any:
    from app.main import app

    return app


@pytest.fixture(autouse=True)
def _ml_and_analytics_on_test_database(
    monkeypatch: pytest.MonkeyPatch,
    analytics_session_factory: sessionmaker[Any],
    tmp_path: Any,
) -> Iterator[None]:
    for target in (
        "app.workers.tasks.reconcile.get_analytics_session_factory",
        "app.workers.tasks.intelligence_common.get_analytics_session_factory",
    ):
        monkeypatch.setattr(target, lambda: analytics_session_factory)
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={"ml_artifacts_dir": tmp_path})
    monkeypatch.setattr("app.workers.tasks.intelligence_common.get_settings", lambda: settings)
    yield


def test_every_scheduled_task_is_classified() -> None:
    scheduled = {entry["task"] for entry in beat.BEAT_SCHEDULE.values()}
    classified = FAN_OUT.keys() | PLATFORM.keys()
    assert scheduled - classified == set(), (
        f"Tâches de beat.py à classer : {scheduled - classified}"
    )
    assert classified - scheduled == set(), f"Entrées sans tâche : {classified - scheduled}"


@pytest.mark.parametrize("fan_out", sorted(FAN_OUT))
def test_a_subtask_for_a_changes_nothing_in_b_and_reruns_cleanly(
    fan_out: str, pair: tuple[DemoCompany, DemoCompany], owner_engine: Engine
) -> None:
    a, b = pair
    subtask = FAN_OUT[fan_out]
    b_before = owner_snapshot(owner_engine, b.company_id)

    subtask(str(a.company_id))
    a_once = owner_snapshot(owner_engine, a.company_id)
    subtask(str(a.company_id))
    a_twice = owner_snapshot(owner_engine, a.company_id)

    b_after = owner_snapshot(owner_engine, b.company_id)
    changed = sorted(table for table in b_before if b_before[table] != b_after[table])
    assert changed == [], f"{fan_out} lancée pour A a modifié chez B : {changed}"
    counts_once = {table: rows for table, (rows, _) in a_once.items() if table != "job_runs"}
    counts_twice = {table: rows for table, (rows, _) in a_twice.items() if table != "job_runs"}
    assert counts_once == counts_twice, f"{fan_out} relancée a laissé un doublon"


def test_one_failing_company_neither_stops_the_others_nor_hides_its_failure(
    pair: tuple[DemoCompany, DemoCompany],
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = pair
    real = reconcile.inventory_service.rebuild_stock

    def flaky(session: Any, ctx: Any) -> Any:
        if ctx.company_id == a.company_id:
            raise RuntimeError("panne provoquée pour A")
        return real(session, ctx)

    monkeypatch.setattr(reconcile.inventory_service, "rebuild_stock", flaky)
    monkeypatch.setattr(reconcile, "each_company", lambda *args: iter([a.company_id, b.company_id]))
    # Exécution réelle de Celery, sans courtier : chaque sous-tâche est isolée comme
    # elle le serait dans le worker (une exception ne remonte pas dans l'éventail).
    monkeypatch.setattr(
        reconcile.rebuild_stock, "delay", lambda *args: reconcile.rebuild_stock.apply(args)
    )

    assert reconcile.rebuild_stock_all() == 2

    def last_run(company: DemoCompany) -> tuple[str, str | None]:
        with owner_engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.company_id', :c, true)"),
                {"c": str(company.company_id)},
            )
            row = connection.execute(
                text(
                    "SELECT status::text, error FROM job_runs "
                    "WHERE job = 'reconcile.rebuild_stock' AND company_id = :c "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"c": company.company_id},
            ).one()
            return str(row[0]), row[1]

    status_a, error_a = last_run(a)
    status_b, _ = last_run(b)
    assert status_a == "failed"
    assert error_a is not None and "RuntimeError" in error_a
    assert "panne provoquée" not in error_a, "le message ne doit jamais être gardé (ADR 0077)"
    assert status_b == "ok"
