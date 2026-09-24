"""Schémas du module Finance.

Ces vues servent au détail d'une vente, à son reçu, et à la traçabilité inverse d'un
remboursement (§ 5.4). Finance ne rend jamais un `return_no` : elle est **sous** Sales
dans l'ordre des dépendances et ne connaît des retours que leur identifiant.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.money import Amount

#: Les cinq moyens par lesquels de l'argent entre ou sort réellement (§ 8.1).
#: `offset` en est **exclu** : une vente ne s'encaisse pas en compensation.
type PaymentMethod = Literal["cash", "mobile_money", "bank_transfer", "card", "cheque"]

#: Ce qu'un gérant peut choisir pour régler un retour : les cinq moyens, ou la
#: compensation d'une dette du client, qui ne fait bouger aucune caisse (ADR 0024).
type RefundMethod = PaymentMethod | Literal["offset"]

#: Ce que la colonne `payments.method` peut valoir en lecture, `offset` compris.
type StoredPaymentMethod = RefundMethod

#: Marque des écritures **sans flux de caisse**. Les états de trésorerie des phases
#: 07 et 08 les excluent sur ce seul critère ; les lettrages, eux, restent exacts.
OFFSET_METHOD: Literal["offset"] = "offset"


class PaymentRead(BaseModel):
    """Encaissement ou décaissement, tel qu'il apparaît sur une vente."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    direction: Literal["inflow", "outflow"]
    method: StoredPaymentMethod
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


class RefundLinkRead(BaseModel):
    """Lettrage retour ↔ paiement : « quel retour a provoqué cette sortie » (§ 5.4)."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    sale_return_id: UUID
    payment_id: UUID
    amount: Amount
    created_at: datetime
