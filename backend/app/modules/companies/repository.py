"""Accès aux données du module Companies."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext
from app.modules.companies.models import Company

#: Les cinq colonnes que `coges_app` lit de `support_sessions` (révision 0029) : ni
#: qui, ni pourquoi. La RLS borne à l'entreprise du contexte.
_OPEN_SUPPORT_SESSION = text(
    """
    SELECT started_at, expires_at FROM support_sessions
    WHERE ended_at IS NULL AND expires_at > clock_timestamp()
    """
)


class CompanyRepository:
    """`companies` n'a pas de colonne `company_id` : le filtre porte sur `id`."""

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def get_current(self) -> Company | None:
        """Entreprise du contexte. La RLS garantit qu'aucune autre n'est atteignable."""
        stmt = select(Company).where(
            Company.id == self.ctx.company_id, Company.deleted_at.is_(None)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def open_support_session(self) -> tuple[datetime, datetime] | None:
        """L'accès support en cours (ADR 0092), début et fin, ou rien."""
        row = self.session.execute(_OPEN_SUPPORT_SESSION).one_or_none()
        return None if row is None else (row.started_at, row.expires_at)
