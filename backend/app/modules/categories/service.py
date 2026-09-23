"""Façade de services du module Categories.

C'est ici que vivent les invariants et la transaction — jamais dans le router, qui
ne fait que de l'HTTP, ni dans le repository, qui ne fait que des requêtes.

`Categories` ne dépend d'aucun autre module (Diagramme 3) : la règle « on ne
supprime pas une catégorie encore utilisée par un produit » est donc portée par un
trigger de la migration 0003, dont le SQLSTATE est traduit ici (ADR 0014).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import BusinessRuleError, NotFoundError, sqlstate
from app.core.search import normalise_term
from app.core.tenancy import TenantContext
from app.modules.categories.models import Category
from app.modules.categories.repository import CategoryRepository
from app.modules.categories.schemas import CategoryCreate, CategoryUpdate

# --------------------------------------------------------------- erreurs métier
# Une classe par règle, avec son code stable en anglais et son message en français.


class CategoryNameTakenError(BusinessRuleError):
    code = "category_name_taken"
    default_message = "Une catégorie porte déjà ce nom au même niveau."


class CategoryCycleError(BusinessRuleError):
    code = "category_cycle"
    default_message = "Une catégorie ne peut pas être rangée sous l'une de ses sous-catégories."


class CategoryHasChildrenError(BusinessRuleError):
    code = "category_has_children"
    default_message = "Cette catégorie contient des sous-catégories."


class CategoryNotEmptyError(BusinessRuleError):
    code = "category_not_empty"
    default_message = "Cette catégorie contient des produits actifs."


#: SQLSTATE levés par `categories_guard_soft_delete()` (migration 0003).
_GUARD_ERRORS: dict[str, type[BusinessRuleError]] = {
    "CG001": CategoryHasChildrenError,
    "CG002": CategoryNotEmptyError,
}


# ------------------------------------------------------------------- lectures


def list_categories(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    parent_id: UUID | None = None,
) -> tuple[Sequence[Category], int]:
    """Page de catégories du tenant, filtrée et recherchée."""
    repository = CategoryRepository(session, ctx)
    term = normalise_term(search)
    items = repository.page_live(page=page, page_size=page_size, search=term, parent_id=parent_id)
    return items, repository.count_live(search=term, parent_id=parent_id)


def get_category(session: Session, ctx: TenantContext, category_id: UUID) -> Category:
    """Catégorie du tenant courant. Celle d'une autre entreprise donne 404."""
    category = CategoryRepository(session, ctx).get_live(category_id)
    if category is None:
        raise NotFoundError("Catégorie introuvable.")
    return category


def assert_exists(session: Session, ctx: TenantContext, category_id: UUID) -> None:
    """Façade pour les modules qui référencent une catégorie (Products).

    Lève 404 si la catégorie n'existe pas **ou** appartient à une autre entreprise.
    La FK composite `products_category_fk` refuserait de toute façon l'écriture ;
    cet appel sert à répondre une erreur lisible plutôt qu'une violation de FK.
    """
    get_category(session, ctx, category_id)


# ------------------------------------------------------------------- écritures


def _assert_name_is_free(
    repository: CategoryRepository,
    name: str,
    parent_id: UUID | None,
    *,
    excluding: UUID | None = None,
) -> None:
    """Unicité du nom sous un même parent.

    Contrôle applicatif pour le message ; l'unicité réelle est garantie par
    l'index `categories_name_uq`, qui resterait le dernier mot en concurrence.
    """
    existing = repository.get_by_name(name, parent_id)
    if existing is not None and existing.id != excluding:
        raise CategoryNameTakenError(details={"name": name})


def _assert_parent_is_valid(
    repository: CategoryRepository,
    parent_id: UUID | None,
    *,
    moving: UUID | None = None,
) -> None:
    """Parent existant, du même tenant, et qui ne referme pas l'arbre sur lui-même."""
    if parent_id is None:
        return
    if repository.get_live(parent_id) is None:
        raise NotFoundError("Catégorie parente introuvable.")
    if moving is not None and moving in repository.self_and_ancestor_ids(parent_id):
        raise CategoryCycleError(details={"category_id": str(moving)})


def create_category(
    session: Session,
    ctx: TenantContext,
    payload: CategoryCreate,
) -> Category:
    """Crée une catégorie, éventuellement sous un parent du même tenant."""
    repository = CategoryRepository(session, ctx)
    _assert_parent_is_valid(repository, payload.parent_id)
    _assert_name_is_free(repository, payload.name, payload.parent_id)

    category = repository.add(
        Category(company_id=ctx.company_id, name=payload.name, parent_id=payload.parent_id)
    )
    session.flush()
    return category


def update_category(
    session: Session,
    ctx: TenantContext,
    category_id: UUID,
    payload: CategoryUpdate,
) -> Category:
    """Renomme une catégorie ou la déplace dans l'arbre."""
    repository = CategoryRepository(session, ctx)
    category = get_category(session, ctx, category_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return category

    # `parent_id` absent du corps = inchangé ; `parent_id: null` = remontée à la racine.
    parent_id = changes.get("parent_id", category.parent_id)
    name = changes.get("name", category.name)

    if "parent_id" in changes:
        _assert_parent_is_valid(repository, parent_id, moving=category.id)
    if changes.keys() & {"name", "parent_id"}:
        _assert_name_is_free(repository, name, parent_id, excluding=category.id)

    category.name = name
    category.parent_id = parent_id
    session.flush()
    return category


def delete_category(
    session: Session,
    ctx: TenantContext,
    category_id: UUID,
    *,
    ip_address: str | None = None,
) -> Category:
    """Suppression **logique**, auditée, refusée si la catégorie est encore utilisée.

    Le contrôle des sous-catégories est fait ici pour rendre la main sans toucher à
    la base ; le trigger `categories_guard_soft_delete` reste l'autorité, y compris
    pour les produits, que ce module n'a pas le droit d'interroger.
    """
    repository = CategoryRepository(session, ctx)
    category = get_category(session, ctx, category_id)

    if repository.count_live_children(category.id) > 0:
        raise CategoryHasChildrenError(details={"category_id": str(category.id)})

    # L'identifiant est retenu **avant** le flush : si le trigger refuse,
    # PostgreSQL annule la transaction et tout accès à un attribut expiré de
    # `category` émettrait une requête sur une transaction morte.
    audited_category_id = str(category.id)
    before = {"name": category.name, "deleted_at": category.deleted_at}
    category.deleted_at = datetime.now(UTC)
    try:
        session.flush()
    except DBAPIError as exc:
        guard = _GUARD_ERRORS.get(sqlstate(exc) or "")
        if guard is None:
            raise
        raise guard(details={"category_id": audited_category_id}) from exc

    audit_critical(
        session,
        ctx,
        action=AuditAction.DELETE,
        entity_table="categories",
        entity_id=category.id,
        before=before,
        after={"name": category.name, "deleted_at": category.deleted_at},
        ip_address=ip_address,
    )
    return category
