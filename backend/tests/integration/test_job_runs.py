"""Trace des tâches planifiées et ping « homme mort » (ADR 0077)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.workers import pings
from app.workers.jobs import tracked_job
from tests.integration.ops_harness import as_ops, ops_settings
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.usefixtures("workers_bound_to_test_database")

PING_URL = "https://hc-ping.example/uuid"


@pytest.fixture
def pinged(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """URLs réellement appelées par les pings, sans réseau."""
    calls: list[str] = []
    monkeypatch.setattr(pings, "_open", calls.append)
    return calls


def _runs(owner_engine: Engine, job: str) -> list[Any]:
    return as_ops(
        owner_engine,
        "SELECT status::text AS status, error, company_id, finished_at FROM job_runs "
        "WHERE job = :job ORDER BY id",
        {"job": job},
    )


def test_failing_task_leaves_a_failed_run_and_pings_fail(
    owner_engine: Engine, pinged: list[str], monkeypatch: pytest.MonkeyPatch, tenant_a: Tenant
) -> None:
    """Une tâche qui lève : trace `failed` sans le message, puis `GET <url>/fail`."""
    job = f"test.failing.{uuid4().hex[:8]}"
    monkeypatch.setattr(pings, "get_settings", lambda: ops_settings(job_ping_urls={job: PING_URL}))

    @tracked_job(job)
    def failing(company_id: str) -> None:
        raise ValueError("Awa Diop doit 87 500 F")

    with pytest.raises(ValueError):
        failing(str(tenant_a.company_id))

    [run] = _runs(owner_engine, job)
    assert run.status == "failed"
    assert run.error == "ValueError"
    assert run.company_id == tenant_a.company_id
    assert run.finished_at is not None
    assert pinged == [PING_URL + "/fail"]


def test_sql_error_keeps_only_the_sqlstate(owner_engine: Engine, pinged: list[str]) -> None:
    """Une erreur SQL garde son SQLSTATE, jamais le texte qui peut citer une valeur."""
    job = f"test.sql.{uuid4().hex[:8]}"

    @tracked_job(job)
    def failing() -> None:
        raise IntegrityError("INSERT …", {}, type("Orig", (Exception,), {"sqlstate": "23505"})())

    with pytest.raises(IntegrityError):
        failing()
    [run] = _runs(owner_engine, job)
    assert run.error == "IntegrityError (SQLSTATE 23505)"


def test_successful_task_leaves_an_ok_run_and_pings(
    owner_engine: Engine, pinged: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    job = f"test.ok.{uuid4().hex[:8]}"
    monkeypatch.setattr(pings, "get_settings", lambda: ops_settings(job_ping_urls={job: PING_URL}))

    @tracked_job(job)
    def succeeding() -> int:
        return 3

    assert succeeding() == 3
    [run] = _runs(owner_engine, job)
    assert (run.status, run.error, run.company_id) == ("ok", None, None)
    assert pinged == [PING_URL]


def test_subtask_pings_its_fan_out_only_on_failure(
    owner_engine: Engine, pinged: list[str], monkeypatch: pytest.MonkeyPatch, tenant_a: Tenant
) -> None:
    """Le succès d'une entreprise ne dit rien des autres : seul l'échec pingue l'éventail."""
    parent = f"test.fan_out.{uuid4().hex[:8]}"
    monkeypatch.setattr(
        pings, "get_settings", lambda: ops_settings(job_ping_urls={parent: PING_URL})
    )

    @tracked_job(f"{parent}.sub", ping_as=parent)
    def sub(company_id: str, fail: bool) -> None:
        if fail:
            raise RuntimeError("boom")

    sub(str(tenant_a.company_id), False)
    assert pinged == []
    with pytest.raises(RuntimeError):
        sub(str(tenant_a.company_id), True)
    assert pinged == [PING_URL + "/fail"]


def test_task_runs_even_if_the_trace_cannot_be_written(monkeypatch: pytest.MonkeyPatch) -> None:
    """La trace ne fait jamais échouer la tâche."""

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("base injoignable")

    monkeypatch.setattr("app.workers.jobs.tenant_transaction", broken)

    @tracked_job("test.no_trace")
    def task() -> str:
        return "fait"

    assert task() == "fait"


def test_runtime_role_cannot_read_job_runs(app_engine: Engine) -> None:
    """`coges_app` n'a aucun droit sur la table : seulement les fonctions de `coges_ops`."""
    with app_engine.connect() as connection, pytest.raises(Exception, match="permission denied"):
        connection.execute(text("SELECT count(*) FROM job_runs"))
