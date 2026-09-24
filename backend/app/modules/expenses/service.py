"""Façade de services du module Expenses.

Invariants et transaction ici, jamais dans le router. La transaction n'est ni
ouverte ni validée par ce module : c'est la dépendance `get_tenant_session` qui l'a
ouverte et qui la validera.

Ce que ce module ne fait pas : régler une dépense. Un décaissement s'écrit dans
`payments` avec `expense_id`, et une dette fournisseur s'ouvre à la main — les deux
appartiennent à `finance`, dont Expenses dépend (Diagramme 3).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.codes import next_document_number
from app.core.errors import BusinessRuleError, NotFoundError
from app.core.events.outbox import emit
from app.core.events.types import EventType
from app.core.tenancy import TenantContext
from app.modules.expenses.events import EXPENSE_AGGREGATE, expense_created_payload
from app.modules.expenses.models import Expense, ExpenseCategory
from app.modules.expenses.repository import (
    ExpenseCategoryRepository,
    ExpenseRepository,
    ExpenseTotalsRepository,
)
from app.modules.expenses.schemas import (
    ExpenseCategoryCreate,
    ExpenseCategoryUpdate,
    ExpenseCreate,
    ExpenseRead,
    ExpenseUpdate,
)
from app.modules.suppliers import service as suppliers_service

#: Type de document de la numérotation (`D-000001`, ADR 0021).
DOCUMENT_TYPE = "expense"

# --------------------------------------------------------------- erreurs métier


class ExpenseCategoryNameTakenError(BusinessRuleError):
    code = "expense_category_name_taken"
    default_message = "Une catégorie de dépense porte déjà ce nom."


class ExpenseCategoryInUseError(BusinessRuleError):
    code = "expense_category_in_use"
    default_message = "Cette catégorie porte encore des dépenses : elle ne peut pas changer."


# ------------------------------------------------------------------- catégories


def list_categories(
    session: Session, ctx: TenantContext, *, page: int, page_size: int
) -> tuple[Sequence[ExpenseCategory], int]:
    repository = ExpenseCategoryRepository(session, ctx)
    return repository.page_ordered(page=page, page_size=page_size), repository.count_all()


def get_category(session: Session, ctx: TenantContext, category_id: UUID) -> ExpenseCategory:
    """Catégorie du tenant courant. Celle d'une autre entreprise donne 404."""
    category = ExpenseCategoryRepository(session, ctx).get(category_id)
    if category is None:
        raise NotFoundError("Catégorie de dépense introuvable.")
    return category


def create_category(
    session: Session, ctx: TenantContext, payload: ExpenseCategoryCreate
) -> ExpenseCategory:
    """Ouvre une famille de charges.

    Aucun audit critique ni événement : une catégorie n'est pas une donnée
    financière, c'est un vocabulaire. Ce sont les dépenses qu'elle range qui le sont.
    """
    repository = ExpenseCategoryRepository(session, ctx)
    if repository.get_by_name(payload.name) is not None:
        raise ExpenseCategoryNameTakenError(details={"name": payload.name})

    category = repository.add(
        ExpenseCategory(company_id=ctx.company_id, name=payload.name, kind=payload.kind)
    )
    session.flush()
    return category


def update_category(
    session: Session,
    ctx: TenantContext,
    category_id: UUID,
    payload: ExpenseCategoryUpdate,
) -> ExpenseCategory:
    """Renomme une famille, ou corrige sa nature.

    Changer `kind` alors que des dépenses y sont rangées **réécrirait le passé** :
    une charge classée variable en janvier deviendrait fixe rétroactivement, et la
    ventilation de tous les mois déjà présentés changerait. Le refus est donc la
    règle, et la sortie est de créer une nouvelle catégorie.
    """
    repository = ExpenseCategoryRepository(session, ctx)
    category = get_category(session, ctx, category_id)
    changes = payload.model_dump(exclude_unset=True)

    name = changes.get("name")
    if name is not None and name != category.name:
        if repository.get_by_name(name, excluding=category_id) is not None:
            raise ExpenseCategoryNameTakenError(details={"name": name})
        category.name = name

    kind = changes.get("kind")
    if kind is not None and kind != category.kind:
        if repository.count_live_expenses(category_id) > 0:
            raise ExpenseCategoryInUseError(details={"category_id": str(category_id)})
        category.kind = kind

    session.flush()
    return category


# --------------------------------------------------------------------- dépenses


def list_expenses(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    period_from: date | None = None,
    period_to: date | None = None,
    category_id: UUID | None = None,
    supplier_id: UUID | None = None,
) -> tuple[Sequence[Row[tuple[Expense, str, str]]], int]:
    """Page de dépenses vivantes, jointes à leur catégorie."""
    repository = ExpenseRepository(session, ctx)
    items = repository.page_live(
        page=page,
        page_size=page_size,
        period_from=period_from,
        period_to=period_to,
        category_id=category_id,
        supplier_id=supplier_id,
    )
    total = repository.count_live(
        period_from=period_from,
        period_to=period_to,
        category_id=category_id,
        supplier_id=supplier_id,
    )
    return items, total


def get_expense(session: Session, ctx: TenantContext, expense_id: UUID) -> Expense:
    """Dépense vivante du tenant. Celle d'une autre entreprise donne 404."""
    expense = ExpenseRepository(session, ctx).get_live(expense_id)
    if expense is None:
        raise NotFoundError("Dépense introuvable.")
    return expense


def build_read(session: Session, ctx: TenantContext, expense: Expense) -> ExpenseRead:
    """Vue publique d'une dépense, sa catégorie jointe.

    `kind` n'est pas stocké sur la dépense (§ 8.6) : il est lu sur la catégorie à
    chaque fois. C'est le prix d'une seule source de vérité pour la nature d'une
    charge.
    """
    category = ExpenseRepository(session, ctx).category_of(expense)
    return ExpenseRead(
        id=expense.id,
        expense_no=expense.expense_no,
        category_id=expense.category_id,
        category_name=category.name,
        kind=category.kind,
        supplier_id=expense.supplier_id,
        label=expense.label,
        amount=expense.amount,
        spent_at=expense.spent_at,
        created_at=expense.created_at,
    )


def assert_exists(session: Session, ctx: TenantContext, expense_id: UUID) -> None:
    """Façade pour les modules qui rattachent une écriture à une dépense (Finance).

    La FK composite `payments_expense_fk` refuserait de toute façon l'écriture ;
    cet appel sert à rendre un 404 lisible plutôt qu'une violation de contrainte.
    """
    get_expense(session, ctx, expense_id)


def _audited(expense: Expense) -> dict[str, str | None]:
    """État d'une dépense tel qu'il est consigné en audit critique."""
    return {
        "expense_no": expense.expense_no,
        "category_id": str(expense.category_id),
        "supplier_id": None if expense.supplier_id is None else str(expense.supplier_id),
        "label": expense.label,
        "amount": str(expense.amount),
        "spent_at": expense.spent_at.isoformat(),
    }


def create_expense(
    session: Session,
    ctx: TenantContext,
    payload: ExpenseCreate,
    *,
    ip_address: str | None = None,
) -> Expense:
    """Constate une charge. Écriture financière : audit critique et événement."""
    category = get_category(session, ctx, payload.category_id)
    if payload.supplier_id is not None:
        suppliers_service.assert_exists(session, ctx, payload.supplier_id)

    expense = ExpenseRepository(session, ctx).add(
        Expense(
            company_id=ctx.company_id,
            expense_no=next_document_number(session, ctx, DOCUMENT_TYPE),
            category_id=payload.category_id,
            supplier_id=payload.supplier_id,
            label=payload.label,
            amount=payload.amount,
            spent_at=payload.spent_at,
            created_by=ctx.user_id,
        )
    )
    session.flush()

    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT,
        entity_table="expenses",
        entity_id=expense.id,
        after=_audited(expense),
        ip_address=ip_address,
    )
    emit(
        session,
        ctx,
        event_type=EventType.EXPENSE_CREATED,
        aggregate_type=EXPENSE_AGGREGATE,
        aggregate_id=expense.id,
        payload=expense_created_payload(
            expense_id=expense.id,
            expense_no=expense.expense_no,
            category_id=expense.category_id,
            kind=category.kind,
            amount=expense.amount,
            spent_at=expense.spent_at,
        ),
    )
    return expense


def update_expense(
    session: Session,
    ctx: TenantContext,
    expense_id: UUID,
    payload: ExpenseUpdate,
    *,
    ip_address: str | None = None,
) -> Expense:
    """Corrige une charge. Audit critique avec la valeur avant et après."""
    expense = get_expense(session, ctx, expense_id)
    before = _audited(expense)
    changes = payload.model_dump(exclude_unset=True)

    if "category_id" in changes and changes["category_id"] is not None:
        get_category(session, ctx, changes["category_id"])
        expense.category_id = changes["category_id"]
    if "supplier_id" in changes:
        if changes["supplier_id"] is not None:
            suppliers_service.assert_exists(session, ctx, changes["supplier_id"])
        expense.supplier_id = changes["supplier_id"]
    for field in ("label", "amount", "spent_at"):
        if changes.get(field) is not None:
            setattr(expense, field, changes[field])

    session.flush()
    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="expenses",
        entity_id=expense.id,
        before=before,
        after=_audited(expense),
        ip_address=ip_address,
    )
    return expense


def delete_expense(
    session: Session,
    ctx: TenantContext,
    expense_id: UUID,
    *,
    ip_address: str | None = None,
) -> None:
    """Supprime **logiquement** une charge, sous audit critique.

    Jamais de suppression physique : `coges_app` n'a pas le droit `DELETE`, et une
    charge effacée sans trace est une trésorerie qu'on ne peut plus expliquer. Le
    numéro reste consommé — la suite des pièces émises ne se réécrit pas.
    """
    expense = get_expense(session, ctx, expense_id)
    before = _audited(expense)
    expense.deleted_at = datetime.now(UTC)
    session.flush()
    audit_critical(
        session,
        ctx,
        action=AuditAction.DELETE,
        entity_table="expenses",
        entity_id=expense.id,
        before=before,
        ip_address=ip_address,
    )


# ------------------------------------- façade de restitution (bande E)


def totals_by_kind(
    session: Session, ctx: TenantContext, *, period_from: date, period_to: date
) -> dict[str, Decimal]:
    """Charges de la période, ventilées `fixed` / `variable`.

    Façade **lecture seule** pour la bande E : Analytics compose, Expenses calcule
    sur ses propres tables.
    """
    return ExpenseTotalsRepository(session, ctx).totals_by_kind(
        period_from=period_from, period_to=period_to
    )
