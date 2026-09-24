"""Modèles du module Expenses. Privés : aucun autre module ne les importe."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, Text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Date

from app.core.database import NOW, IdentifiedTenantBase

#: ENUM PostgreSQL de la révision 0001. `create_type=False` : le type existe déjà,
#: SQLAlchemy ne doit surtout pas tenter de le créer.
EXPENSE_KIND = PG_ENUM("fixed", "variable", name="expense_kind", create_type=False)


class ExpenseCategory(IdentifiedTenantBase):
    """Famille de charges, et sa nature.

    C'est la **catégorie** qui porte `fixed` / `variable`, et non la dépense
    (§ 8.6). Un loyer est fixe parce que c'est un loyer, pas parce qu'on l'a coché.
    """

    __tablename__ = "expense_categories"

    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(EXPENSE_KIND)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


class Expense(IdentifiedTenantBase):
    """Charge constatée, numérotée et rattachée à une catégorie."""

    __tablename__ = "expenses"

    expense_no: Mapped[str] = mapped_column(Text)
    category_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    label: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    spent_at: Mapped[date] = mapped_column(Date)
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
