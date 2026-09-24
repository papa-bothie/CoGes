"""Schémas du module Sales.

Montants, quantités et taux sont des `Decimal` en Python et des **chaînes** en JSON
(types annotés de `app/core/money.py`). Aucun flottant ne traverse l'API.

Ce que le client n'envoie **jamais** : le prix unitaire, le taux de taxe, le coût
unitaire, les totaux. Le prix vient de `product_prices`, le taux de `products` ou de
la TVA de l'entreprise, le coût du CMP, et les totaux sont produits par la base
(§ 4.4 et § 4.5). Un client qui pourrait fixer son prix ne serait pas un client.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.money import Amount, Quantity, Rate, UnitCost
from app.modules.finance.schemas import DebtRead, PaymentMethod, PaymentRead

CANCEL_REASON_MAX_LENGTH = 500

#: Les trois valeurs de l'ENUM `sale_status` (§ 8.1). « Retournée » n'en est pas
#: une : c'est une information dérivée, exposée par `has_returns`.
type SaleStatus = Literal["draft", "confirmed", "cancelled"]

#: Bornes des `CHECK` du § 8.4, doublées côté schéma : le client reçoit un 422 qui
#: nomme le champ, la base reste l'autorité pour qui n'entre pas par l'API.
type SaleQty = Annotated[Quantity, Field(gt=Decimal("0"))]
type LineDiscount = Annotated[Amount, Field(ge=Decimal("0"))]
type PaidAmount = Annotated[Amount, Field(ge=Decimal("0"))]

type CancelReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=CANCEL_REASON_MAX_LENGTH),
]


# ------------------------------------------------------------------- entrées


class SaleCreate(BaseModel):
    """Ouverture d'un brouillon. Aucun effet de bord (§ 5.1)."""

    model_config = ConfigDict(extra="forbid")

    customer_id: UUID | None = None
    #: Date métier de la vente. Par défaut `now()`. Le mouvement de stock, lui,
    #: est daté de la confirmation : c'est à ce moment que la marchandise part.
    sold_at: datetime | None = None


class SaleUpdate(BaseModel):
    """Ce qu'on peut encore changer sur un brouillon : le client et la date."""

    model_config = ConfigDict(extra="forbid")

    customer_id: UUID | None = None
    sold_at: datetime | None = None


class SaleItemCreate(BaseModel):
    """Ajout d'une ligne à un brouillon."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    qty: SaleQty
    discount: LineDiscount = Decimal("0")


class SaleItemUpdate(BaseModel):
    """Correction d'une ligne de brouillon."""

    model_config = ConfigDict(extra="forbid")

    qty: SaleQty | None = None
    discount: LineDiscount | None = None


class SaleConfirm(BaseModel):
    """Règlement présenté à la confirmation.

    `paid_amount` à 0 est une vente entièrement à crédit : elle exige un client.
    `paid_amount` égal au total est une vente payée comptant, sans dette.
    """

    model_config = ConfigDict(extra="forbid")

    paid_amount: PaidAmount = Decimal("0")
    method: PaymentMethod = "cash"
    #: Échéance de la dette éventuelle. Sans échéance, la dette reste exigible.
    due_date: datetime | None = None


class SaleCancel(BaseModel):
    """Annulation. Le motif est obligatoire : `sales_cancel_coherent` l'exige."""

    model_config = ConfigDict(extra="forbid")

    reason: CancelReason


# ------------------------------------------------------------------- sorties


class SaleItemRead(BaseModel):
    """Ligne de vente, avec ses montants calculés par la base."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    product_id: UUID
    price_id: UUID | None
    qty: Quantity
    unit_price: Amount
    #: `numeric(14,4)` : le CMP a besoin de quatre décimales.
    unit_cost: UnitCost
    discount: Amount
    tax_rate: Rate
    net_amount: Amount
    tax_amount: Amount
    line_total: Amount


class SaleRead(BaseModel):
    """Vente en liste : l'en-tête, sans ses lignes."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    sale_no: str
    customer_id: UUID | None
    status: SaleStatus
    sold_at: datetime
    subtotal: Amount
    discount_total: Amount
    tax_total: Amount
    total: Amount
    paid_total: Amount
    #: Solde restant dû. Dérivé, pas stocké : `total - paid_total`.
    balance: Amount
    #: La vente a au moins un retour. Dérivé : ce n'est pas un statut de la base.
    has_returns: bool
    cancel_reason: str | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None


class SaleDetail(SaleRead):
    """Vente complète : en-tête, lignes, règlements et dette éventuelle."""

    items: list[SaleItemRead]
    payments: list[PaymentRead]
    debt: DebtRead | None


class SalePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SaleRead]
    page: int
    page_size: int
    total: int


class ReceiptCompany(BaseModel):
    """En-tête du reçu : qui vend."""

    model_config = ConfigDict(extra="forbid")

    name: str
    currency: str


class ReceiptCustomer(BaseModel):
    """Client du reçu, absent sur une vente au comptoir."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str | None
    name: str


class ReceiptLine(BaseModel):
    """Ligne du reçu : ce que le client a acheté, au prix qu'il a payé."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    sku: str
    name: str
    qty: Quantity
    unit_price: Amount
    discount: Amount
    tax_rate: Rate
    tax_amount: Amount
    line_total: Amount


class ReceiptRead(BaseModel):
    """Reçu simple d'une vente confirmée.

    Un JSON complet, que le frontend met en page : l'API ne rend ni PDF ni HTML
    (ADR 0022). Tout y est figé — le reçu d'une vente de l'an dernier reste exact
    même si les prix, les taux et les noms ont changé depuis.
    """

    model_config = ConfigDict(extra="forbid")

    sale_id: UUID
    sale_no: str
    status: SaleStatus
    sold_at: datetime
    confirmed_at: datetime | None
    company: ReceiptCompany
    customer: ReceiptCustomer | None
    lines: list[ReceiptLine]
    subtotal: Amount
    discount_total: Amount
    tax_total: Amount
    total: Amount
    paid_total: Amount
    balance: Amount
    payments: list[PaymentRead]
