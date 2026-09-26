"""Schémas du module Finance.

Ces vues servent au détail d'une vente, à son reçu, à la traçabilité inverse d'un
remboursement (§ 5.4) et, depuis la phase 07, aux écritures financières autonomes :
encaisser, décaisser, affecter à une ou plusieurs dettes.

Finance ne rend jamais un `return_no` ni un `sale_no` : elle est **sous** Sales dans
l'ordre des dépendances et ne connaît des ventes et des retours que leur identifiant.

Les bornes de saisie doublent les `CHECK` du § 8.6 : le client reçoit un 422 qui
nomme le champ au lieu d'un 500 sur violation de contrainte (ADR 0010).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    # Révision 0012 : un paiement annulé reste lisible, et dit par quoi il l'a été.
    cancelled: bool = False
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    cancellation_id: UUID | None = None
    #: Renseigné sur la ligne d'annulation elle-même : le paiement qu'elle neutralise.
    reversal_of_payment_id: UUID | None = None


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


#: Sens d'un mouvement d'argent (§ 8.1). Le sens n'est **jamais** porté par un
#: montant négatif : `CHECK (amount > 0)` l'interdit de toute façon.
type CashDirection = Literal["inflow", "outflow"]

#: Nature d'une partie à une dette (§ 8.1).
type PartyType = Literal["customer", "supplier"]

#: Statut d'une dette (§ 8.1).
type DebtStatus = Literal["open", "partially_paid", "paid", "written_off"]

#: `CHECK (amount > 0)` et `CHECK (principal > 0)` du § 8.6.
type PositiveAmount = Annotated[Amount, Field(gt=Decimal("0"))]

#: Longueur minimale du motif d'un abandon de créance. Renoncer à un actif sans
#: pouvoir dire pourquoi n'est pas une décision, c'est une perte.
REASON_MIN_LENGTH = 10
REASON_MAX_LENGTH = 500

#: Bornes de saisie des champs libres d'un paiement.
REFERENCE_MAX_LENGTH = 100
NOTE_MAX_LENGTH = 500

#: Nombre maximal de dettes qu'un seul versement peut éteindre. Aucun texte ne le
#: fixe ; la borne existe pour qu'une requête absurde soit refusée avant d'ouvrir
#: cinquante verrous `FOR UPDATE` dans la transaction d'un caissier.
MAX_ALLOCATIONS = 20


class AllocationInput(BaseModel):
    """Part d'un versement affectée à une dette."""

    model_config = ConfigDict(extra="forbid")

    debt_id: UUID
    amount: PositiveAmount


class PaymentCreate(BaseModel):
    """Encaissement ou décaissement saisi à la main.

    `method` exclut `offset` : une compensation ne se saisit pas, elle naît d'un
    retour (ADR 0024).
    """

    model_config = ConfigDict(extra="forbid")

    direction: CashDirection
    method: PaymentMethod
    amount: PositiveAmount
    paid_at: datetime | None = None
    reference: Annotated[str, Field(max_length=REFERENCE_MAX_LENGTH)] | None = None
    note: Annotated[str, Field(max_length=NOTE_MAX_LENGTH)] | None = None
    sale_id: UUID | None = None
    expense_id: UUID | None = None
    allocations: Annotated[list[AllocationInput], Field(max_length=MAX_ALLOCATIONS)] = []

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        """Ce qui se voit sans lire la base : contexte unique, date non future.

        Le contexte est doublé par `payments_context_one` ; la date ne l'est par
        rien — le § 8.6 ne borne pas `paid_at`. Un encaissement daté de demain
        n'est pourtant pas un encaissement, c'est une prévision.
        """
        if self.sale_id is not None and self.expense_id is not None:
            raise ValueError("Un paiement porte au plus un contexte : une vente ou une dépense.")
        if self.paid_at is not None and self.paid_at > datetime.now(UTC):
            raise ValueError("La date d'un paiement ne peut pas être dans le futur.")
        return self


class AllocationRead(BaseModel):
    """Lettrage paiement ↔ dette."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    payment_id: UUID
    debt_id: UUID
    amount: Amount
    created_at: datetime


class PaymentDetail(BaseModel):
    """Vue complète d'un paiement, ses affectations comprises."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    direction: CashDirection
    method: StoredPaymentMethod
    amount: Amount
    paid_at: datetime
    sale_id: UUID | None
    expense_id: UUID | None
    sale_return_id: UUID | None
    reference: str | None
    note: str | None
    created_at: datetime
    allocations: list[AllocationRead]
    # Révision 0012 : un paiement annulé reste lisible, et dit par quoi il l'a été.
    cancelled: bool = False
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    cancellation_id: UUID | None = None
    #: Renseigné sur la ligne d'annulation elle-même : le paiement qu'elle neutralise.
    reversal_of_payment_id: UUID | None = None


class PaymentCancel(BaseModel):
    """Annulation d'un paiement erroné : le motif n'est pas facultatif (ADR 0038)."""

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[
        str,
        Field(min_length=REASON_MIN_LENGTH, max_length=REASON_MAX_LENGTH),
    ]


class PaymentPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PaymentDetail]
    page: int
    page_size: int
    total: int


class DebtCreate(BaseModel):
    """Dette ouverte à la main : engagement fournisseur, ou créance hors vente.

    Une dette née d'une vente n'entre pas par ici : elle naît de la confirmation
    (§ 5.1 étape 8), et `sale_id` n'est donc pas saisissable.
    """

    model_config = ConfigDict(extra="forbid")

    party_type: PartyType
    principal: PositiveAmount
    customer_id: UUID | None = None
    supplier_id: UUID | None = None
    expense_id: UUID | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def _check_party(self) -> Self:
        """XOR client / fournisseur, doublé par `debts_party_xor` en base."""
        if self.party_type == "customer" and (
            self.customer_id is None or self.supplier_id is not None
        ):
            raise ValueError("Une créance client exige un client, et lui seul.")
        if self.party_type == "supplier" and (
            self.supplier_id is None or self.customer_id is not None
        ):
            raise ValueError("Une dette fournisseur exige un fournisseur, et lui seul.")
        return self


class DebtWriteOff(BaseModel):
    """Abandon d'une créance : le motif n'est pas facultatif."""

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[
        str,
        Field(min_length=REASON_MIN_LENGTH, max_length=REASON_MAX_LENGTH),
    ]


class DebtDetail(BaseModel):
    """Vue complète d'une dette, ses règlements compris."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    party_type: PartyType
    customer_id: UUID | None
    supplier_id: UUID | None
    sale_id: UUID | None
    expense_id: UUID | None
    principal: Amount
    amount_paid: Amount
    balance: Amount
    due_date: date | None
    status: DebtStatus
    closed_at: datetime | None
    created_at: datetime
    allocations: list[AllocationRead]


class DebtPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DebtDetail]
    page: int
    page_size: int
    total: int
