"""Schémas du module Customers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

from app.core.money import Amount
from app.core.validation import reject_explicit_nulls

NAME_MAX_LENGTH = 200
CODE_MAX_LENGTH = 32
PHONE_MAX_LENGTH = 40

type CustomerName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH)
]
#: Mis en majuscules : `customers_code_uq` est sensible à la casse, et « cli-1 »
#: puis « CLI-1 » désigneraient deux clients pour un seul code affiché.
type CustomerCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_upper=True, min_length=1, max_length=CODE_MAX_LENGTH
    ),
]
type Phone = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PHONE_MAX_LENGTH)
]
#: Borne du `CHECK (credit_limit >= 0)` du § 8.3, portée aussi par le schéma pour
#: sortir en 422 plutôt qu'en 500.
type CreditLimit = Annotated[Amount, Field(ge=Decimal("0"))]


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    code: str | None
    name: str
    phone: str | None
    email: str | None
    #: `null` = aucun plafond ; `0` = vente à crédit interdite.
    credit_limit: CreditLimit | None
    created_at: datetime


class CustomerCreate(BaseModel):
    """`code` omis : le serveur en attribue un (`CLI-0001`), modifiable ensuite."""

    model_config = ConfigDict(extra="forbid")

    name: CustomerName
    code: CustomerCode | None = None
    phone: Phone | None = None
    email: EmailStr | None = None
    credit_limit: CreditLimit | None = None


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CustomerName | None = None
    code: CustomerCode | None = None
    phone: Phone | None = None
    email: EmailStr | None = None
    credit_limit: CreditLimit | None = None

    @model_validator(mode="after")
    def _no_null_on_required_fields(self) -> Self:
        reject_explicit_nulls(self, ("name",))
        return self


class CustomerPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CustomerRead]
    page: int
    page_size: int
    total: int
