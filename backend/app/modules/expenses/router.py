"""Routes HTTP du module Expenses. Aucune requête SQL ici.

Une dépense ne se supprime pas physiquement : `DELETE /expenses/{id}` pose
`deleted_at` et laisse une ligne d'audit. Le numéro reste consommé.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core import idempotency
from app.core.deps import TenantSession, client_ip, require_permission
from app.core.idempotency import IdempotencyKey
from app.core.repository import MAX_PAGE_SIZE
from app.modules.expenses import service
from app.modules.expenses.schemas import (
    ExpenseCategoryCreate,
    ExpenseCategoryPage,
    ExpenseCategoryRead,
    ExpenseCategoryUpdate,
    ExpenseCreate,
    ExpensePage,
    ExpenseRead,
    ExpenseUpdate,
)

#: Une catégorie est un vocabulaire, une dépense est une écriture : deux cycles de
#: vie distincts, donc deux préfixes.
categories_router = APIRouter(prefix="/expense-categories", tags=["expenses"])
router = APIRouter(prefix="/expenses", tags=["expenses"])

#: Identifie l'écriture dans `idempotency_keys` : une même clé sur deux endpoints
#: différents est un abus visible, pas un rejeu.
CREATE_EXPENSE_ENDPOINT = "POST /api/v1/expenses"


# ------------------------------------------------------------------- catégories


@categories_router.get("", response_model=ExpenseCategoryPage)
def list_categories(
    tenant: Annotated[TenantSession, Depends(require_permission("expenses:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> ExpenseCategoryPage:
    """Familles de charges de l'entreprise."""
    items, total = service.list_categories(
        tenant.session, tenant.ctx, page=page, page_size=page_size
    )
    return ExpenseCategoryPage(
        items=[ExpenseCategoryRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@categories_router.post("", response_model=ExpenseCategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: ExpenseCategoryCreate,
    tenant: Annotated[TenantSession, Depends(require_permission("expenses:create"))],
) -> ExpenseCategoryRead:
    """Ouvre une famille de charges, fixe ou variable."""
    category = service.create_category(tenant.session, tenant.ctx, payload)
    return ExpenseCategoryRead.model_validate(category)


@categories_router.get("/{category_id}", response_model=ExpenseCategoryRead)
def get_category(
    category_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("expenses:read"))],
) -> ExpenseCategoryRead:
    category = service.get_category(tenant.session, tenant.ctx, category_id)
    return ExpenseCategoryRead.model_validate(category)


@categories_router.patch("/{category_id}", response_model=ExpenseCategoryRead)
def update_category(
    category_id: UUID,
    payload: ExpenseCategoryUpdate,
    tenant: Annotated[TenantSession, Depends(require_permission("expenses:update"))],
) -> ExpenseCategoryRead:
    """Renomme une famille. Sa nature ne change plus dès qu'elle porte des charges."""
    category = service.update_category(tenant.session, tenant.ctx, category_id, payload)
    return ExpenseCategoryRead.model_validate(category)


# --------------------------------------------------------------------- dépenses


@router.get("", response_model=ExpensePage)
def list_expenses(
    tenant: Annotated[TenantSession, Depends(require_permission("expenses:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    period_from: Annotated[date | None, Query(alias="from")] = None,
    period_to: Annotated[date | None, Query(alias="to")] = None,
    category_id: Annotated[UUID | None, Query()] = None,
    supplier_id: Annotated[UUID | None, Query()] = None,
) -> ExpensePage:
    """Charges constatées, de la plus récente à la plus ancienne."""
    rows, total = service.list_expenses(
        tenant.session,
        tenant.ctx,
        page=page,
        page_size=page_size,
        period_from=period_from,
        period_to=period_to,
        category_id=category_id,
        supplier_id=supplier_id,
    )
    return ExpensePage(
        items=service.build_reads(tenant.session, tenant.ctx, rows),
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("expenses:create"))],
    idempotency_key: IdempotencyKey,
) -> Response:
    """Constate une charge. Écriture financière : clé d'idempotence obligatoire.

    Avec `payment`, la charge et son décaissement (montant de la charge) s'écrivent
    dans la même transaction ; `payments:create` est alors exigé en plus.
    """
    replay = idempotency.reserve(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        endpoint=CREATE_EXPENSE_ENDPOINT,
        payload=payload,
    )
    if replay is not None:
        return idempotency.replay_response(replay)

    expense = service.create_expense(
        tenant.session, tenant.ctx, payload, ip_address=client_ip(request)
    )
    return idempotency.completed(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        status_code=status.HTTP_201_CREATED,
        model=service.build_read(tenant.session, tenant.ctx, expense),
    )


@router.get("/{expense_id}", response_model=ExpenseRead)
def get_expense(
    expense_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("expenses:read"))],
) -> ExpenseRead:
    expense = service.get_expense(tenant.session, tenant.ctx, expense_id)
    return service.build_read(tenant.session, tenant.ctx, expense)


@router.patch("/{expense_id}", response_model=ExpenseRead)
def update_expense(
    expense_id: UUID,
    payload: ExpenseUpdate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("expenses:update"))],
) -> ExpenseRead:
    """Corrige une charge, sous audit critique."""
    expense = service.update_expense(
        tenant.session, tenant.ctx, expense_id, payload, ip_address=client_ip(request)
    )
    return service.build_read(tenant.session, tenant.ctx, expense)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: UUID,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("expenses:delete"))],
) -> Response:
    """Suppression **logique**, auditée. La ligne reste, le numéro aussi."""
    service.delete_expense(tenant.session, tenant.ctx, expense_id, ip_address=client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
