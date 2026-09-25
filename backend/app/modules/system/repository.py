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
