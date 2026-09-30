"""Schémas du module Expenses.

`extra="forbid"` partout, et chaque `CHECK` du § 8.6 doublé d'une borne de saisie :
le client reçoit un 422 qui nomme le champ, la base reste le dernier mot pour qui
n'entre pas par l'API (ADR 0010).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.money import Amount
from app.modules.finance.schemas import REFERENCE_MAX_LENGTH, PaymentMethod

#: Longueurs maximales. La base n'impose que « non vide » ; la borne haute est une
#: règle de saisie, elle appartient au schéma.
NAME_MAX_LENGTH = 120
LABEL_MAX_LENGTH = 200

#: Nature d'une famille de charges : ENUM `expense_kind` du § 8.1.
type ExpenseKind = Literal["fixed", "variable"]

#: Rogné **avant** d'être mesuré : une saisie de blancs est refusée par le schéma
#: (422) et non par le `CHECK (length(btrim(...)) > 0)`, qui sortirait en 500.
type CategoryName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH)
]
type ExpenseLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=LABEL_MAX_LENGTH)
]

#: `CHECK (amount > 0)` du § 8.6 : jamais de montant négatif ni nul. Une dépense
#: qui s'annule est supprimée logiquement, elle ne devient pas zéro.
type ExpenseAmount = Annotated[Amount, Field(gt=Decimal("0"))]


def _check_spent_at(value: date | None) -> date | None:
    """Double le `CHECK (spent_at <= current_date + 1)` du § 8.6.

    La tolérance d'un jour est celle de la base, reprise à l'identique : elle
    absorbe l'écart entre le fuseau de l'entreprise et l'UTC du serveur. Au-delà,
    ce n'est plus une charge constatée mais une prévision, et la V1 n'en fait pas.

    Sans ce contrôle, la contrainte sortirait en 500 au lieu d'un 422 qui nomme le
    champ (ADR 0010, décision 4).
    """
    if value is not None and value > date.today() + timedelta(days=1):
        raise ValueError("La date d'une dépense ne peut pas être dans le futur.")
    return value


class ExpenseCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    name: str
    kind: ExpenseKind
    created_at: datetime


class ExpenseCategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CategoryName
    kind: ExpenseKind


class ExpenseCategoryUpdate(BaseModel):
    """Modification partielle : champ absent = inchangé (`exclude_unset`)."""

    model_config = ConfigDict(extra="forbid")

    name: CategoryName | None = None
    kind: ExpenseKind | None = None


class ExpenseCategoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ExpenseCategoryRead]
    page: int
    page_size: int
    total: int


class ExpenseRead(BaseModel):
    """Vue publique d'une dépense.

    `kind` est repris de la catégorie : il n'est pas stocké sur la dépense, mais
    c'est lui qui compte à l'écran comme dans la ventilation de la trésorerie.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    expense_no: str
    category_id: UUID
    category_name: str
    kind: ExpenseKind
    supplier_id: UUID | None
    label: str
    amount: Amount
    spent_at: date
    created_at: datetime
    #: Décaissé pour cette dépense, paiements annulés exclus (ADR 0053). Le reste à
    #: régler n'est **pas** servi : l'écran compare, il ne soustrait pas.
    amount_paid: Amount = Decimal("0")


class ExpensePaymentInput(BaseModel):
    """Règlement immédiat d'une dépense : le montant est celui de la dépense."""

    model_config = ConfigDict(extra="forbid")

    method: PaymentMethod
    paid_at: datetime | None = None
    reference: Annotated[str, Field(max_length=REFERENCE_MAX_LENGTH)] | None = None

    @model_validator(mode="after")
    def _check_paid_at(self) -> Self:
        if self.paid_at is not None and self.paid_at > datetime.now(UTC):
            raise ValueError("La date d'un paiement ne peut pas être dans le futur.")
        return self


class ExpenseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID
    label: ExpenseLabel
    amount: ExpenseAmount
    spent_at: date
    supplier_id: UUID | None = None
    #: Présent : la dépense et son décaissement s'écrivent dans la même transaction,
    #: sous la même clé d'idempotence (ADR 0053).
    payment: ExpensePaymentInput | None = None

    @model_validator(mode="after")
    def _check_date(self) -> Self:
        _check_spent_at(self.spent_at)
        return self


class ExpenseUpdate(BaseModel):
    """Modification partielle.

    `supplier_id: null` explicitement transmis détache le fournisseur ; champ
    absent = inchangé. Le montant reste modifiable : une dépense est une saisie,
    pas une pièce émise à un tiers.
    """

    model_config = ConfigDict(extra="forbid")

    category_id: UUID | None = None
    label: ExpenseLabel | None = None
    amount: ExpenseAmount | None = None
    spent_at: date | None = None
    supplier_id: UUID | None = None

    @model_validator(mode="after")
    def _check_date(self) -> Self:
        _check_spent_at(self.spent_at)
        return self


class ExpensePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ExpenseRead]
    page: int
    page_size: int
    total: int
