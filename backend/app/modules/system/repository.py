"""Requêtes du module System — l'outbox de l'entreprise du contexte.

`business_events` est sous RLS comme le reste : cette lecture passe par `coges_app`
et ne voit donc **que** l'entreprise du contexte. Le relais, lui, franchit la RLS par
des fonctions `SECURITY DEFINER` — deux chemins, deux portées, et c'est voulu : un
gérant n'a aucune raison de compter les événements de ses concurrents.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import TextClause, text
from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext

_OUTBOX_HEALTH = text(
    """
    SELECT
      count(*) FILTER (WHERE published_at IS NULL AND attempts < :max_attempts) AS pending,
      count(*) FILTER (WHERE published_at IS NULL AND attempts >= :max_attempts) AS dead_lettered,
      count(*) FILTER (WHERE published_at IS NOT NULL)                          AS published,
      min(occurred_at) FILTER (WHERE published_at IS NULL)  AS oldest_pending_at,
      max(published_at)                                     AS last_published_at
      FROM business_events
     WHERE company_id = :company_id
    """
)


class OutboxHealthRepository:
    """Compteurs de l'outbox. Aucune écriture : l'API ne publie ni ne rejoue."""

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def health(self, *, max_attempts: int) -> dict[str, object]:
        row = self.session.execute(
            _OUTBOX_HEALTH,
            {"company_id": self.ctx.company_id, "max_attempts": max_attempts},
        ).one()
        return {
            "pending": int(row.pending),
            "dead_lettered": int(row.dead_lettered),
            "published": int(row.published),
            "oldest_pending_at": row.oldest_pending_at,
            "last_published_at": row.last_published_at,
        }


_OUTBOX_LAG = text("SELECT pending, dead_lettered, oldest_pending_at FROM outbox_lag()")
_JOB_RUNS_LATEST = text(
    """
    SELECT job, last_status, last_started_at, last_finished_at, last_ok_at,
           companies_ok, companies_failed
      FROM job_runs_latest(make_interval(secs => :stale_seconds))
    """
)

_JOB_RUNS_HISTORY = text(
    """
    SELECT id, job, status, started_at, finished_at, error, per_company, total
      FROM job_runs_history(:job, :status, make_interval(secs => :stale_seconds),
                            :limit, :offset)
    """
)
_DEAD_LETTERS = text(
    "SELECT id, event_type, occurred_at, attempts, total FROM outbox_dead_letters(:limit, :offset)"
)


class PlatformHealthRepository:
    """Lectures de plate-forme, sans entreprise (ADR 0077).

    Des fonctions `SECURITY DEFINER` seulement : `coges_app` n'a aucun droit sur
    `job_runs` et ne voit `business_events` que sous RLS ; `coges_app_platform` n'a
    aucun droit sur l'une ni l'autre. Aucun identifiant d'entreprise ne revient.
    L'historique et le rebut ne s'exécutent que sous `coges_app_platform` (ADR 0090).
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def outbox_lag(self) -> dict[str, object]:
        row = self.session.execute(_OUTBOX_LAG).one()
        return {
            "pending": int(row.pending),
            "dead_lettered": int(row.dead_lettered),
            "oldest_pending_at": row.oldest_pending_at,
        }

    def job_runs_latest(self, *, stale_seconds: int) -> list[dict[str, object]]:
        rows = self.session.execute(_JOB_RUNS_LATEST, {"stale_seconds": stale_seconds}).all()
        return [dict(row._mapping) for row in rows]

    def job_runs_history(
        self, *, job: str | None, status: str | None, stale_seconds: int, limit: int, offset: int
    ) -> tuple[list[dict[str, object]], int]:
        params = {"job": job, "status": status, "stale_seconds": stale_seconds}
        return self._page(_JOB_RUNS_HISTORY, params, limit=limit, offset=offset)

    def dead_letters(self, *, limit: int, offset: int) -> tuple[list[dict[str, object]], int]:
        return self._page(_DEAD_LETTERS, {}, limit=limit, offset=offset)

    def _page(
        self, query: TextClause, params: dict[str, Any], *, limit: int, offset: int
    ) -> tuple[list[dict[str, object]], int]:
        """Lignes sans la colonne `total` (`count(*) OVER ()`), et ce total.

        Au-delà de la dernière page, aucune ligne ne porte le total : on le relit sur
        la première, pour que l'écran sache combien il y en a.
        """
        rows = self.session.execute(query, {**params, "limit": limit, "offset": offset}).all()
        if not rows and offset:
            first = self.session.execute(query, {**params, "limit": 1, "offset": 0}).all()
            return [], int(first[0].total) if first else 0
        total = int(rows[0].total) if rows else 0
        return [{k: v for k, v in row._mapping.items() if k != "total"} for row in rows], total
