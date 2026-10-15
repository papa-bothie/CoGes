"""Chaque tâche de `beat.py` se relance à la main sans effet de bord (ADR 0077).

Le guide `docs/runbooks/workers.md` dit « relancez la tâche » : c'est sûr seulement si
la seconde exécution ne change rien de plus que la première. Chaque test exécute la
tâche deux fois et compare.

Les sous-tâches de CoGes Intelligence ne sont relancées ici qu'au niveau de leur
éventail : le rejeu du pipeline sur le même jour est **T33**
(`test_t33_pipeline_replay.py`), qui compte les lignes avant et après.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import redis
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.workers.beat import BEAT_SCHEDULE
from app.workers.tasks import (
    analytics,
    exports,
    ml_features,
    ml_infer,
    ml_train,
    notifications,
    reconcile,
    system,
)
from tests.conftest import DemoCompany

pytestmark = pytest.mark.usefixtures("workers_bound_to_test_database")


@pytest.fixture(autouse=True)
def _analytics_tasks_on_test_database(
    monkeypatch: pytest.MonkeyPatch, analytics_session_factory: sessionmaker[Any]
) -> None:
    """`check_revenue` ouvre sa session analytique par son propre import."""
    monkeypatch.setattr(
        "app.workers.tasks.reconcile.get_analytics_session_factory",
        lambda: analytics_session_factory,
    )


def _twice[T](task: Callable[[], T]) -> tuple[T, T]:
    return task(), task()


def test_every_scheduled_task_is_covered_here() -> None:
    """Une tâche ajoutée à `BEAT_SCHEDULE` doit recevoir son test de relance ci-dessous."""
    covered = {
        "reconcile.ensure_audit_partitions",
        "reconcile.purge_idempotency_keys",
        "exports.sweep_all",
        "reconcile.rebuild_stock_all",
        "reconcile.rebuild_recent_facts_all",
        "ml_features.compute_all",
        "ml_train.train_all",
        "ml_infer.infer_all",
        "notifications.scan_due_debts_all",
        "reconcile.check_revenue_all",
        "system.purge_job_runs",
        "system.beat_tick",
    }
    assert {entry["task"] for entry in BEAT_SCHEDULE.values()} == covered


# ------------------------------------------------------------ tâches de plate-forme


def test_audit_partitions_three_months_ahead_and_rerun(owner_engine: Engine) -> None:
    """Le mois courant et les trois suivants existent ; la relance n'en crée pas d'autre."""
    first, second = _twice(reconcile.ensure_audit_partitions)
    assert first == second

    month = datetime.now(UTC).date().replace(day=1)
    expected = []
    for _ in range(4):
        expected.append(f"audit_logs_{month:%Y}m{month:%m}")
        month = (month + timedelta(days=32)).replace(day=1)
    assert second == f"{(month - timedelta(days=1)).replace(day=1)}"
    with owner_engine.connect() as connection:
        found = set(
            connection.execute(
                text("SELECT relname FROM pg_class WHERE relname = ANY(:names)"),
                {"names": expected},
            ).scalars()
        )
        partitions = connection.execute(
            text("SELECT count(*) FROM pg_inherits WHERE inhparent = 'public.audit_logs'::regclass")
        ).scalar_one()
    assert found == set(expected)
    reconcile.ensure_audit_partitions()
    with owner_engine.connect() as connection:
        again = connection.execute(
            text("SELECT count(*) FROM pg_inherits WHERE inhparent = 'public.audit_logs'::regclass")
        ).scalar_one()
    assert again == partitions


def test_purge_idempotency_keys_rerun() -> None:
    """La seconde purge ne trouve plus rien à retirer."""
    _, second = _twice(reconcile.purge_idempotency_keys)
    assert second == 0


def test_purge_job_runs_rerun() -> None:
    _, second = _twice(system.purge_job_runs)
    assert second == 0


def test_beat_tick_rerun(ops_redis: redis.Redis) -> None:
    """Le tic n'écrit qu'une heure dans Redis : le relancer la remplace."""
    assert _twice(system.beat_tick) == ("tick", "tick")
    assert ops_redis.exists("coges:ops:beat_tick") == 1


# ------------------------------------------------------------------ éventails


@pytest.mark.parametrize(
    ("fan_out", "subtask"),
    [
        (reconcile.rebuild_stock_all, reconcile.rebuild_stock),
        (reconcile.rebuild_recent_facts_all, analytics.rebuild_recent_facts),
        (reconcile.check_revenue_all, reconcile.check_revenue),
        (exports.sweep_all, exports.sweep),
        (notifications.scan_due_debts_all, notifications.scan_due_debts),
        (ml_features.compute_all, ml_features.compute),
        (ml_train.train_all, ml_train.train),
        (ml_infer.infer_all, ml_infer.infer),
    ],
    ids=lambda task: getattr(task, "name", ""),
)
def test_fan_out_rerun_enqueues_the_same_subtasks(
    fan_out: Any, subtask: Any, monkeypatch: pytest.MonkeyPatch, company_alpha: DemoCompany
) -> None:
    """Relancé, un éventail enfile exactement les mêmes sous-tâches, rien d'autre."""
    enqueued: list[tuple[Any, ...]] = []
    monkeypatch.setattr(subtask, "delay", lambda *args: enqueued.append(args))

    first = fan_out()
    calls_first = list(enqueued)
    enqueued.clear()
    second = fan_out()

    assert first == second
    assert enqueued == calls_first
    assert (str(company_alpha.company_id),) == next(
        call[:1] for call in enqueued if call[0] == str(company_alpha.company_id)
    )


# ------------------------------------------------------ sous-tâches par entreprise


def test_rebuild_stock_rerun_finds_nothing_to_fix(company_alpha: DemoCompany) -> None:
    _, second = _twice(lambda: reconcile.rebuild_stock(str(company_alpha.company_id)))
    assert second == 0


def test_rebuild_recent_facts_rerun(
    company_alpha: DemoCompany, analytics_session_factory: sessionmaker[Any]
) -> None:
    from tests.conftest import read_scalar_in_tenant

    count = "SELECT count(*) FROM daily_sales_facts"
    company = str(company_alpha.company_id)
    analytics.rebuild_recent_facts(company, 7)
    before = read_scalar_in_tenant(analytics_session_factory, company_alpha.company_id, count)
    analytics.rebuild_recent_facts(company, 7)
    after = read_scalar_in_tenant(analytics_session_factory, company_alpha.company_id, count)
    assert after == before


def test_check_revenue_rerun(company_alpha: DemoCompany) -> None:
    assert _twice(lambda: reconcile.check_revenue(str(company_alpha.company_id))) == ("ok", "ok")


def test_sweep_exports_rerun(company_alpha: DemoCompany, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exports.build_sales, "delay", lambda **kwargs: None)
    _, second = _twice(lambda: exports.sweep(str(company_alpha.company_id)))
    assert second == 0


def test_scan_due_debts_rerun_does_not_notify_twice(company_alpha: DemoCompany) -> None:
    """Le dédoublonnage de 24 h fait de la relance un geste sans effet."""
    _, second = _twice(lambda: notifications.scan_due_debts(str(company_alpha.company_id)))
    assert second == 0
