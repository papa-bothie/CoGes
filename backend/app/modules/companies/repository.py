"""Accès aux données du module Companies."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.companies.models import Company


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
