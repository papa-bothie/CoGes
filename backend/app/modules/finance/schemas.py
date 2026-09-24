"""Schémas du module Finance.

Aucun schéma d'entrée en phase 05 : Finance n'a pas encore de router, elle n'est
appelée que par la façade. Ces vues servent au détail d'une vente et à son reçu.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.money import Amount

#: Les cinq moyens de paiement de l'ENUM `pay_method` (§ 8.1).
type PaymentMethod = Literal["cash", "mobile_money", "bank_transfer", "card", "cheque"]


class PaymentRead(BaseModel):
    """Encaissement ou décaissement, tel qu'il apparaît sur une vente."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    direction: Literal["inflow", "outflow"]
    method: PaymentMethod
    amount: Amount
    paid_at: datetime
    reference: str | None


class DebtRead(BaseModel):
    """Dette client née d'une vente à crédit."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    customer_id: UUID | None
    principal: Amount
    amount_paid: Amount
    balance: Amount
    due_date: date | None
    status: Literal["open", "partially_paid", "paid", "written_off"]
    closed_at: datetime | None
