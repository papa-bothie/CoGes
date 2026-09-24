"""Modèles du module Finance. Privés : aucun autre module ne les importe."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Computed, Date, DateTime, Numeric, Text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import NOW, IdentifiedTenantBase

# Types créés par la révision 0001 : l'ORM les référence sans jamais les redéclarer.
CASH_DIRECTION = PG_ENUM("inflow", "outflow", name="cash_direction", create_type=False)
PAY_METHOD = PG_ENUM(
    "cash",
    "mobile_money",
    "bank_transfer",
    "card",
    "cheque",
    # Révision 0008 : marque d'une écriture **sans flux de caisse** (compensation
    # d'une dette par un retour), et non un sixième moyen de payer (ADR 0024).
    "offset",
    name="pay_method",
    create_type=False,
)
PARTY_TYPE = PG_ENUM("customer", "supplier", name="party_type", create_type=False)
DEBT_STATUS = PG_ENUM(
    "open", "partially_paid", "paid", "written_off", name="debt_status", create_type=False
)


class Payment(IdentifiedTenantBase):
    """Mouvement de trésorerie, rattaché à sa pièce d'origine."""

    __tablename__ = "payments"

    direction: Mapped[str] = mapped_column(CASH_DIRECTION)
    method: Mapped[str] = mapped_column(PAY_METHOD)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    sale_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    expense_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    sale_return_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


class Debt(IdentifiedTenantBase):
    """Créance ou dette envers un tiers. `principal` n'est jamais réécrit (§ 5.5)."""

    __tablename__ = "debts"

    party_type: Mapped[str] = mapped_column(PARTY_TYPE)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    sale_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    expense_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    principal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    #: Maintenu par le trigger `pa_rollup` depuis `payment_allocations`, jamais en Python.
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), Computed("principal - amount_paid", persisted=True)
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(DEBT_STATUS)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


class PaymentAllocation(IdentifiedTenantBase):
    """Lettrage paiement ↔ dette (§ 5.5).

    Le solde de la dette n'est pas écrit ici : `pa_rollup` recalcule `amount_paid`,
    `status` et `closed_at` à chaque écriture, et `balance` est une colonne générée.
    """

    __tablename__ = "payment_allocations"

    payment_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    debt_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


class SaleReturnRefund(IdentifiedTenantBase):
    """Lettrage retour ↔ paiement, symétrique de `PaymentAllocation` (§ 4.7).

    Une simple FK `payments.sale_return_id` ne suffisait pas : elle interdirait de
    rembourser deux retours d'un même versement, et d'échelonner un remboursement en
    deux versements. `sale_return_id` reste un `uuid` nu — Finance est **sous** Sales
    dans l'ordre des dépendances et ne connaît pas `SaleReturn`.
    """

    __tablename__ = "sale_return_refunds"

    sale_return_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    payment_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
