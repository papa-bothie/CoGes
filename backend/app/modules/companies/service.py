"""Façade de services du module Companies.

Les autres modules passent **par ici**, jamais par le repository ni les modèles.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import NotFoundError
from app.core.tenancy import TenantContext
from app.modules.companies.logo import normalize_logo
from app.modules.companies.models import Company, CompanyLogo
from app.modules.companies.repository import CompanyRepository
from app.modules.companies.schemas import (
    DEFAULT_REORDER_POINT,
    DEFAULT_TAX_RATE,
    RECEIPT_FORMAT,
    SHOP_FIELDS,
    CompanyLogoRead,
    CompanyRead,
    CompanyUpdate,
    SupportAccessRead,
    SupportAccessWindow,
)

#: Modifier ces champs change l'interprétation de toutes les données suivantes :
#: devise, fuseau, TVA, seuils ; ou ce que les reçus attestent : identifiants fiscaux et
#: coordonnées de la boutique (ADR 0070). L'audit critique est donc obligatoire.
SENSITIVE_FIELDS = ("currency", "timezone", "settings", *SHOP_FIELDS)


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


def receipt_format(session: Session, ctx: TenantContext) -> Literal["ticket", "a4"]:
    """Reçu ouvert par défaut après une vente (écran 24, ADR 0075) ; absent = petit ticket."""
    value = get_current_company(session, ctx).settings.get(RECEIPT_FORMAT)
    return "a4" if value == "a4" else "ticket"


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


def is_suspended(session: Session, ctx: TenantContext) -> bool:
    """L'accès de l'entreprise est-il coupé par l'administration (ADR 0089) ?"""
    return get_current_company(session, ctx).status == "suspended"


def get_timezone(session: Session, ctx: TenantContext) -> str:
    """Fuseau de l'entreprise, pour découper une série en journées vécues.

    Façade pour la bande E : `paid_at` est stocké en UTC, mais une caisse ferme à
    l'heure locale. Sans cette conversion, un encaissement de 23 h tomberait le
    lendemain sur le graphique du gérant.
    """
    return get_current_company(session, ctx).timezone


def describe(session: Session, ctx: TenantContext, company: Company) -> CompanyRead:
    """`CompanyRead`, avec la date du logo (sans charger l'image)."""
    logo_at = CompanyRepository(session, ctx).logo_updated_at()
    return CompanyRead.model_validate(company).model_copy(update={"logo_updated_at": logo_at})


class LogoNotFoundError(NotFoundError):
    code = "logo_not_found"
    default_message = "Aucun logo pour cette boutique."


def _logo_state(logo: CompanyLogo) -> dict[str, Any] | None:
    """Ce que l'audit garde d'un logo : son empreinte et ses dimensions, jamais les octets."""
    if logo.png is None:
        return None
    return {
        "sha256": logo.sha256,
        "width": logo.width,
        "height": logo.height,
        "byte_size": logo.byte_size,
    }


def get_logo_png(session: Session, ctx: TenantContext) -> bytes:
    """Le PNG du logo de l'entreprise, ou 404 `logo_not_found`."""
    logo = CompanyRepository(session, ctx).get_logo()
    if logo is None or logo.png is None:
        raise LogoNotFoundError()
    return logo.png


def set_logo(
    session: Session, ctx: TenantContext, content: bytes, *, ip_address: str | None = None
) -> CompanyLogoRead:
    """Ajoute ou change le logo : image vérifiée et ré-encodée, audit critique (ADR 0111)."""
    normalized = normalize_logo(content)
    logo = CompanyRepository(session, ctx).lock_logo()
    before = _logo_state(logo)
    logo.png = normalized.png
    logo.sha256 = normalized.sha256
    logo.width = normalized.width
    logo.height = normalized.height
    logo.byte_size = normalized.byte_size
    logo.updated_by = ctx.user_id
    session.flush()
    session.refresh(logo)
    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT if before is None else AuditAction.UPDATE,
        entity_table="company_logos",
        entity_id=ctx.company_id,
        before=before,
        after=_logo_state(logo),
        ip_address=ip_address,
    )
    return CompanyLogoRead(
        width=normalized.width, height=normalized.height, updated_at=logo.updated_at
    )


def remove_logo(session: Session, ctx: TenantContext, *, ip_address: str | None = None) -> None:
    """Retire le logo : les octets sont effacés, la ligne reste (pas de DELETE)."""
    logo = CompanyRepository(session, ctx).get_logo(for_update=True)
    before = None if logo is None else _logo_state(logo)
    if logo is None or before is None:
        raise LogoNotFoundError()
    logo.png = logo.sha256 = None
    logo.width = logo.height = logo.byte_size = None
    logo.updated_by = ctx.user_id
    session.flush()
    audit_critical(
        session,
        ctx,
        action=AuditAction.DELETE,
        entity_table="company_logos",
        entity_id=ctx.company_id,
        before=before,
        after=None,
        ip_address=ip_address,
    )


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


def support_access(session: Session, ctx: TenantContext) -> SupportAccessRead:
    """L'accès support en cours dans l'entreprise, pour le bandeau de tous (ADR 0092)."""
    window = CompanyRepository(session, ctx).open_support_session()
    if window is None:
        return SupportAccessRead(session=None)
    return SupportAccessRead(
        session=SupportAccessWindow(started_at=window[0], expires_at=window[1])
    )
