"""Accès aux données du module Expenses.

Requêtes filtrées par tenant, et rien d'autre. Toute lecture part de
`self._select()` (barrière 2, `app/core/repository.py`), qui porte déjà le filtre
`company_id`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, Row, Select, func, select

from app.core.repository import TenantRepository
from app.modules.expenses.models import Expense, ExpenseCategory


class ExpenseCategoryRepository(TenantRepository[ExpenseCategory]):
    model = ExpenseCategory

    def get_by_name(self, name: str, *, excluding: UUID | None = None) -> ExpenseCategory | None:
        """Homonyme dans l'entreprise (contrainte `expense_categories_name_uq`)."""
        stmt = self._select().where(ExpenseCategory.name == name)
        if excluding is not None:
            stmt = stmt.where(ExpenseCategory.id != excluding)
        return self.session.execute(stmt).scalar_one_or_none()

    def count_all(self) -> int:
        return self.count()

    def page_ordered(self, *, page: int, page_size: int) -> Sequence[ExpenseCategory]:
        stmt = (
            self._select()
            .order_by(ExpenseCategory.name)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def count_live_expenses(self, category_id: UUID) -> int:
        """Dépenses vivantes rattachées à cette catégorie."""
        stmt = (
            select(func.count())
            .select_from(Expense)
            .where(
                Expense.company_id == self.ctx.company_id,
                Expense.category_id == category_id,
                Expense.deleted_at.is_(None),
            )
        )
        return int(self.session.execute(stmt).scalar_one())


class ExpenseRepository(TenantRepository[Expense]):
    model = Expense

    def _live(self) -> Select[tuple[Expense]]:
        """Base de toute lecture : tenant + exclusion des suppressions logiques."""
        return self._select().where(Expense.deleted_at.is_(None))

    def _filters(
        self,
        *,
        period_from: date | None,
        period_to: date | None,
        category_id: UUID | None,
        supplier_id: UUID | None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if period_from is not None:
            conditions.append(Expense.spent_at >= period_from)
        if period_to is not None:
            conditions.append(Expense.spent_at <= period_to)
        if category_id is not None:
            conditions.append(Expense.category_id == category_id)
        if supplier_id is not None:
            conditions.append(Expense.supplier_id == supplier_id)
        return conditions

    def get_live(self, expense_id: UUID) -> Expense | None:
        stmt = self._live().where(Expense.id == expense_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def count_live(
        self,
        *,
        period_from: date | None = None,
        period_to: date | None = None,
        category_id: UUID | None = None,
        supplier_id: UUID | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Expense)
            .where(Expense.company_id == self.ctx.company_id, Expense.deleted_at.is_(None))
            .where(
                *self._filters(
                    period_from=period_from,
                    period_to=period_to,
                    category_id=category_id,
                    supplier_id=supplier_id,
                )
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def page_live(
        self,
        *,
        page: int,
        page_size: int,
        period_from: date | None = None,
        period_to: date | None = None,
        category_id: UUID | None = None,
        supplier_id: UUID | None = None,
    ) -> Sequence[Row[tuple[Expense, str, str]]]:
        """Page de dépenses, **jointe à sa catégorie**.

        La jointure est faite ici et non par une relation ORM : un module ne porte
        pas de relation vers les modèles d'un autre, et surtout la vue publique a
        besoin du nom et de la nature à chaque ligne — les charger ligne à ligne
        serait un N+1 sur la page la plus consultée de la finance.
        """
        stmt = (
            select(Expense, ExpenseCategory.name, ExpenseCategory.kind)
            .join(
                ExpenseCategory,
                (ExpenseCategory.company_id == Expense.company_id)
                & (ExpenseCategory.id == Expense.category_id),
            )
            .where(Expense.company_id == self.ctx.company_id, Expense.deleted_at.is_(None))
            .where(
                *self._filters(
                    period_from=period_from,
                    period_to=period_to,
                    category_id=category_id,
                    supplier_id=supplier_id,
                )
            )
            .order_by(Expense.spent_at.desc(), Expense.expense_no.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).all()

    def category_of(self, expense: Expense) -> Row[tuple[str, str]]:
        """Nom et nature de la catégorie d'une dépense, pour sa vue publique."""
        stmt = select(ExpenseCategory.name, ExpenseCategory.kind).where(
            ExpenseCategory.company_id == self.ctx.company_id,
            ExpenseCategory.id == expense.category_id,
        )
        return self.session.execute(stmt).one()


class ExpenseTotalsRepository(TenantRepository[Expense]):
    """Agrégats de charges pour la bande E (lecture seule)."""

    model = Expense

    def totals_by_kind(self, *, period_from: date, period_to: date) -> dict[str, Decimal]:
        """Charges vivantes de la période, ventilées fixe / variable.

        La nature vient de la catégorie (§ 8.6) : une dépense ne la porte pas, et
        la ventilation se fait donc par jointure. Les dépenses supprimées
        logiquement sont exclues — une charge annulée n'a pas pesé.
        """
        stmt = (
            select(ExpenseCategory.kind, func.coalesce(func.sum(Expense.amount), 0))
            .select_from(Expense)
            .join(
                ExpenseCategory,
                (ExpenseCategory.company_id == Expense.company_id)
                & (ExpenseCategory.id == Expense.category_id),
            )
            .where(
                Expense.company_id == self.ctx.company_id,
                Expense.deleted_at.is_(None),
                Expense.spent_at >= period_from,
                Expense.spent_at <= period_to,
            )
            .group_by(ExpenseCategory.kind)
        )
        totals = {"fixed": Decimal("0"), "variable": Decimal("0")}
        for kind, total in self.session.execute(stmt):
            totals[kind] = Decimal(total)
        return totals

    def _joined(self) -> Select[tuple[Expense, str]]:
        return (
            select(Expense, ExpenseCategory.name)
            .join(
                ExpenseCategory,
                (ExpenseCategory.company_id == Expense.company_id)
                & (ExpenseCategory.id == Expense.category_id),
            )
            .where(Expense.company_id == self.ctx.company_id, Expense.deleted_at.is_(None))
        )

    def totals_by_category(
        self, *, period_from: date, period_to: date
    ) -> Sequence[Row[tuple[UUID, str, Decimal]]]:
        """Charges vivantes de la période par catégorie, la plus lourde d'abord."""
        total = func.sum(Expense.amount)
        stmt = (
            select(ExpenseCategory.id, ExpenseCategory.name, total)
            .select_from(Expense)
            .join(
                ExpenseCategory,
                (ExpenseCategory.company_id == Expense.company_id)
                & (ExpenseCategory.id == Expense.category_id),
            )
            .where(
                Expense.company_id == self.ctx.company_id,
                Expense.deleted_at.is_(None),
                Expense.spent_at >= period_from,
                Expense.spent_at <= period_to,
            )
            .group_by(ExpenseCategory.id, ExpenseCategory.name)
            .order_by(total.desc(), ExpenseCategory.name)
        )
        return self.session.execute(stmt).all()

    def largest(self, *, period_from: date, period_to: date) -> Row[tuple[Expense, str]] | None:
        """La plus grosse charge vivante de la période (la cause d'une perte, écran 17)."""
        stmt = (
            self._joined()
            .where(Expense.spent_at >= period_from, Expense.spent_at <= period_to)
            .order_by(Expense.amount.desc(), Expense.spent_at.desc(), Expense.expense_no.desc())
            .limit(1)
        )
        return self.session.execute(stmt).first()

    def heads(self, expense_ids: Sequence[UUID]) -> Sequence[Row[tuple[Expense, str]]]:
        """Dépenses d'un lot, supprimées comprises, jointes au nom de leur catégorie.

        Une dépense supprimée garde son paiement dans la caisse (écran 21) : son nom
        doit rester lisible.
        """
        if not expense_ids:
            return []
        stmt = (
            select(Expense, ExpenseCategory.name)
            .join(
                ExpenseCategory,
                (ExpenseCategory.company_id == Expense.company_id)
                & (ExpenseCategory.id == Expense.category_id),
            )
            .where(Expense.company_id == self.ctx.company_id, Expense.id.in_(list(expense_ids)))
        )
        return self.session.execute(stmt).all()
