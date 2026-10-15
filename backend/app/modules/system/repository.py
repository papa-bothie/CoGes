"""Requêtes du module System — l'outbox de l'entreprise du contexte.

`business_events` est sous RLS comme le reste : cette lecture passe par `coges_app`
et ne voit donc **que** l'entreprise du contexte. Le relais, lui, franchit la RLS par
des fonctions `SECURITY DEFINER` — deux chemins, deux portées, et c'est voulu : un
gérant n'a aucune raison de compter les événements de ses concurrents.
"""

from __future__ import annotations

from sqlalchemy import text
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


class PlatformHealthRepository:
    """Lectures de plate-forme, sans entreprise (ADR 0077).

    Deux fonctions `SECURITY DEFINER`, deux agrégats : `coges_app` n'a aucun droit sur
    `job_runs` et ne voit `business_events` que sous RLS. Aucun identifiant
    d'entreprise ne revient.
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
