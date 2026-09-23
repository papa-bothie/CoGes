"""Schémas du module Suppliers."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NAME_MAX_LENGTH = 200
CODE_MAX_LENGTH = 32
PHONE_MAX_LENGTH = 40
#: Bornes du `CHECK (payment_terms_days BETWEEN 0 AND 365)` du § 8.3.
MIN_PAYMENT_TERMS_DAYS = 0
MAX_PAYMENT_TERMS_DAYS = 365

type SupplierName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH)
]
type SupplierCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_upper=True, min_length=1, max_length=CODE_MAX_LENGTH
    ),
]
type Phone = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PHONE_MAX_LENGTH)
]
type PaymentTermsDays = Annotated[int, Field(ge=MIN_PAYMENT_TERMS_DAYS, le=MAX_PAYMENT_TERMS_DAYS)]


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    code: str | None
    name: str
    phone: str | None
    payment_terms_days: int | None
    created_at: datetime


class SupplierCreate(BaseModel):
    """`code` omis : le serveur en attribue un (`FRN-0001`), modifiable ensuite."""

    model_config = ConfigDict(extra="forbid")

    name: SupplierName
    code: SupplierCode | None = None
    phone: Phone | None = None
    payment_terms_days: PaymentTermsDays | None = None


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: SupplierName | None = None
    code: SupplierCode | None = None
    phone: Phone | None = None
    payment_terms_days: PaymentTermsDays | None = None


class SupplierPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SupplierRead]
    page: int
    page_size: int
    total: int
