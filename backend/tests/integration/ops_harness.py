"""Outils des tests de surveillance (ADR 0077).

`job_runs` n'est lisible par aucun rôle d'exécution : les tests passent par le
propriétaire, qui emprunte `coges_ops` le temps d'une transaction (`SET LOCAL ROLE`,
`coges_owner` en est membre sans héritage). C'est ce que l'application ne fait jamais.
"""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import Settings, get_settings

OPS_TOKEN = "jeton-d-exploitation-de-test-0123456789"


def as_ops(owner_engine: Engine, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    """Exécute `sql` sous `coges_ops` et rend les lignes (vide pour une écriture)."""
    with owner_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE coges_ops"))
        result = connection.execute(text(sql), params or {})
        return list(result.all()) if result.returns_rows else []


def clear_job_runs(owner_engine: Engine) -> None:
    as_ops(owner_engine, "DELETE FROM job_runs")


def add_run(
    owner_engine: Engine,
    job: str,
    *,
    status: str = "ok",
    company_id: Any = None,
    hours_ago: float = 1.0,
    error: str | None = None,
) -> None:
    as_ops(
        owner_engine,
        """
        INSERT INTO job_runs (job, company_id, status, started_at, finished_at, error)
        VALUES (:job, :company_id, CAST(:status AS job_run_status),
                now() - make_interval(secs => :seconds),
                CASE WHEN :status = 'running' THEN NULL
                     ELSE now() - make_interval(secs => :seconds) END,
                :error)
        """,
        {
            "job": job,
            "company_id": company_id,
            "status": status,
            "seconds": hours_ago * 3600,
            "error": error,
        },
    )


def ops_settings(**update: Any) -> Settings:
    values: dict[str, Any] = {"ops_token": SecretStr(OPS_TOKEN)}
    values.update(update)
    return get_settings().model_copy(update=values)
