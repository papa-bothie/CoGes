"""Schémas du module Inventory.

Quantités et coûts sont des `Decimal` en Python et des **chaînes** en JSON (types
annotés de `app/core/money.py`). Aucun flottant ne traverse l'API : un CMP calculé
sur un flottant serait faux, et la valeur de stock avec lui.

Deux refus sont **structurels**, portés par le schéma plutôt que par un `if` du
service : `sale_out` et `customer_return_in` n'existent pas dans `ManualMovementType`.
Ces deux types appartiennent aux flux de vente (phases 05-06), qui passent par
`service.record_movement` sans traverser le router.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.money import Amount, Quantity, UnitCost

NOTE_MAX_LENGTH = 500

#: Tolérance sur la borne haute d'`occurred_at`, alignée sur la révision 0005 :
#: elle absorbe le décalage d'horloge entre l'API et PostgreSQL, rien de plus.
FUTURE_TOLERANCE = timedelta(minutes=5)

#: Les cinq types qu'un humain peut saisir. `sale_out` et `customer_return_in` en
#: sont volontairement absents (voir le docstring du module).
type ManualMovementType = Literal[
    "initial", "purchase_in", "supplier_return_out", "adjustment", "loss"
]
#: Les mêmes, pour un test d'appartenance : seuls ceux-là se corrigent par l'inverse
#: depuis le stock (ADR 0017, complément).
MANUAL_MOVEMENT_TYPES: frozenset[str] = frozenset(
    {"initial", "purchase_in", "supplier_return_out", "adjustment", "loss"}
)
#: Les sept valeurs de l'ENUM `movement_type`, pour la lecture et les filtres.
type MovementType = Literal[
    "initial",
    "purchase_in",
    "sale_out",
    "customer_return_in",
    "supplier_return_out",
    "adjustment",
    "loss",
]

#: Statut d'un article au regard de son seuil de réapprovisionnement.
type StockStatus = Literal["ok", "low", "out"]

type MovementNote = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTE_MAX_LENGTH)
]

# Bornes des `CHECK` du § 8.5, doublées côté schéma : le client reçoit un 422 qui
# nomme le champ, la base reste l'autorité pour qui n'entre pas par l'API.
type MovementUnitCost = Annotated[UnitCost, Field(ge=Decimal("0"))]

#: Types dont le mouvement ne peut être que positif, et négatif (`inv_sign_coherent`).
POSITIVE_TYPES: frozenset[str] = frozenset({"initial", "purchase_in", "customer_return_in"})
NEGATIVE_TYPES: frozenset[str] = frozenset({"sale_out", "supplier_return_out", "loss"})
#: Types qui exigent un motif écrit : ce sont les seules écritures de stock qui ne
#: découlent d'aucun flux métier, et elles passent en audit critique.
TYPES_REQUIRING_NOTE: frozenset[str] = frozenset({"adjustment", "loss"})


class MovementCreate(BaseModel):
    """Saisie d'un mouvement manuel."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    type: ManualMovementType
    qty_delta: Quantity
    #: Obligatoire sur une réception, interdit sur une sortie (le trigger estampille
    #: le CMP), facultatif sur un ajustement positif (défaut : CMP courant, ADR 0016).
    unit_cost: MovementUnitCost | None = None
    supplier_id: UUID | None = None
    note: MovementNote | None = None
    #: Date métier. Par défaut `now()`. Bornée des deux côtés (ADR 0015) : 48 h
    #: d'antidatage au plus, et jamais dans le futur.
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def _check_coherence(self) -> Self:
        """Double les `CHECK` de la base, pour un refus qui nomme le champ."""
        if self.qty_delta == 0:
            raise ValueError("qty_delta : un mouvement de zéro n'a aucun sens.")
        if self.type in POSITIVE_TYPES and self.qty_delta < 0:
            raise ValueError(f"qty_delta : un mouvement « {self.type} » est une entrée (> 0).")
        if self.type in NEGATIVE_TYPES and self.qty_delta > 0:
            raise ValueError(f"qty_delta : un mouvement « {self.type} » est une sortie (< 0).")
        if self.type in TYPES_REQUIRING_NOTE and self.note is None:
            raise ValueError(f"note : un mouvement « {self.type} » exige un motif écrit.")
        if self.qty_delta > 0 and self.type != "adjustment" and self.unit_cost is None:
            raise ValueError("unit_cost : une entrée de stock exige un coût unitaire.")
        if self.qty_delta < 0 and self.unit_cost is not None:
            raise ValueError(
                "unit_cost : une sortie est valorisée au CMP courant, il ne se saisit pas."
            )
        if self.occurred_at is not None:
            if self.occurred_at.tzinfo is None:
                raise ValueError("occurred_at : la date doit porter un fuseau horaire.")
            # Une date future est une faute de frappe, jamais une intention. Non
            # refusée, elle devient le `max(occurred_at)` du produit et bloque tout
            # mouvement ultérieur, l'annulation comprise (ADR 0015).
            if self.occurred_at > datetime.now(UTC) + FUTURE_TOLERANCE:
                raise ValueError("occurred_at : un mouvement ne peut pas être daté dans le futur.")
        return self


class MovementRead(BaseModel):
    """Une ligne du journal, telle qu'elle a été figée."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    product_id: UUID
    type: MovementType
    qty_delta: Quantity
    unit_cost: UnitCost
    ref_type: str | None
    ref_id: UUID | None
    reversal_of_movement_id: UUID | None
    supplier_id: UUID | None
    note: str | None
    occurred_at: datetime
    created_by: UUID | None
    created_at: datetime


class MovementPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MovementRead]
    page: int
    page_size: int
    total: int


class StockLine(BaseModel):
    """Stock valorisé d'un article, joint à sa fiche produit.

    C'est la vue « produits + stock » de l'ADR 0012 : elle vit ici parce que
    Products (bande B) n'a pas le droit de lire le stock (bande C).
    """

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    sku: str
    name: str
    category_id: UUID | None
    category_name: str | None
    qty_on_hand: Quantity
    avg_cost: UnitCost
    stock_value: Amount
    reorder_point: Quantity | None
    status: StockStatus
    last_movement_at: datetime | None


class StockPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[StockLine]
    page: int
    page_size: int
    total: int


class StockRebuildLine(BaseModel):
    """Écart constaté par `rebuild_product_stock` pour un produit."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    qty_ecart: Quantity
    avg_ecart: UnitCost
