"""Façade de services du module Companies.

Les autres modules passent **par ici**, jamais par le repository ni les modèles.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import NotFoundError
from app.core.tenancy import TenantContext
from app.modules.companies.models import Company
from app.modules.companies.repository import CompanyRepository
from app.modules.companies.schemas import DEFAULT_REORDER_POINT, DEFAULT_TAX_RATE, CompanyUpdate

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


def is_tax_enabled(session: Session, ctx: TenantContext) -> bool:
    """La TVA s'applique-t-elle aux ventes de cette entreprise ?

    Façade pour Sales, qui fige `tax_rate` sur chaque ligne à la confirmation.
    Le paramètre vit dans `settings`, où le § 8.2 range tout ce qui est propre à
    l'entreprise ; il n'a pas de colonne.

    **Absent vaut « activée »** (ADR 0022). Le vrai interrupteur est déjà le taux
    du produit, qui vaut 0 par défaut : une entreprise non assujettie ne taxe rien
    sans avoir rien à paramétrer. Mettre `tax_enabled` à `false` devient alors un
    geste explicite, qui force 0 même sur un produit à 18 % — et les entreprises
    créées avant cette phase, dont `settings` vaut `{}`, continuent de vendre
    comme avant.
    """
    setting = get_current_company(session, ctx).settings.get("tax_enabled", True)
    return bool(setting)


def is_intelligence_enabled(session: Session, ctx: TenantContext) -> bool:
    """CoGes Intelligence est-elle active pour cette entreprise ? (ADR 0036)

    **Absent vaut « activée »**, comme `tax_enabled` : les entreprises existantes
    reçoivent leurs prévisions sans rien paramétrer. `false` coupe le pipeline (aucun
    calcul) et masque les blocs prédictifs de l'API, sans rien casser d'autre. Le
    changement passe par `PATCH /companies/current`, déjà sous audit critique.
    """
    setting = get_current_company(session, ctx).settings.get("intelligence_enabled", True)
    return bool(setting)


def default_reorder_point(session: Session, ctx: TenantContext) -> Decimal | None:
    """Seuil d'alerte appliqué à un produit suivi créé sans seuil (ADR 0054), ou `None`."""
    value = get_current_company(session, ctx).settings.get(DEFAULT_REORDER_POINT)
    return None if value is None else Decimal(str(value))


def default_tax_rate(session: Session, ctx: TenantContext) -> Decimal:
    """Taux appliqué à un article créé sans taux (ADR 0066, complément), 0 par défaut."""
    value = get_current_company(session, ctx).settings.get(DEFAULT_TAX_RATE)
    return Decimal("0") if value is None else Decimal(str(value))


def get_current_company(session: Session, ctx: TenantContext) -> Company:
    """Entreprise du contexte, ou 404."""
    company = CompanyRepository(session, ctx).get_current()
    if company is None:
        raise NotFoundError("Entreprise introuvable.")
    return company


def get_timezone(session: Session, ctx: TenantContext) -> str:
    """Fuseau de l'entreprise, pour découper une série en journées vécues.

    Façade pour la bande E : `paid_at` est stocké en UTC, mais une caisse ferme à
    l'heure locale. Sans cette conversion, un encaissement de 23 h tomberait le
    lendemain sur le graphique du gérant.
    """
    return get_current_company(session, ctx).timezone


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
