"""Façade de services du module Companies.

Les autres modules passent **par ici**, jamais par le repository ni les modèles.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import NotFoundError
from app.core.tenancy import TenantContext
from app.modules.companies.models import Company
from app.modules.companies.repository import CompanyRepository
from app.modules.companies.schemas import CompanyUpdate

#: Modifier ces champs change l'interprétation de toutes les données suivantes :
#: devise, fuseau, TVA, seuils. L'audit critique est donc obligatoire.
SENSITIVE_FIELDS = ("currency", "timezone", "settings")


def create_company(
    session: Session,
    ctx: TenantContext,
    *,
    name: str,
    slug: str,
    currency: str = "XOF",
    timezone: str = "Africa/Dakar",
) -> Company:
    """Crée l'entreprise du contexte.

    Le `company_id` est **pré-généré côté serveur** puis posé comme contexte avant
    l'INSERT : la politique `companies_self` accepte alors l'écriture, sans aucun
    contournement de la RLS (ADR 0004). Réservé à l'amorçage (`app.cli`).
    """
    company = Company(
        id=ctx.company_id, name=name, slug=slug, currency=currency, timezone=timezone, settings={}
    )
    session.add(company)
    session.flush()
    return company


def get_current_company(session: Session, ctx: TenantContext) -> Company:
    """Entreprise du contexte, ou 404."""
    company = CompanyRepository(session, ctx).get_current()
    if company is None:
        raise NotFoundError("Entreprise introuvable.")
    return company


def update_current_company(
    session: Session,
    ctx: TenantContext,
    payload: CompanyUpdate,
    *,
    ip_address: str | None = None,
) -> Company:
    """Met à jour les paramètres, avec audit critique **dans la même transaction**."""
    company = get_current_company(session, ctx)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return company

    before: dict[str, Any] = {field: getattr(company, field) for field in changes}
    for field, value in changes.items():
        setattr(company, field, value)
    session.flush()
    after: dict[str, Any] = {field: getattr(company, field) for field in changes}

    if any(field in SENSITIVE_FIELDS for field in changes):
        audit_critical(
            session,
            ctx,
            action=AuditAction.UPDATE,
            entity_table="companies",
            entity_id=company.id,
            before=before,
            after=after,
            ip_address=ip_address,
        )
    return company
