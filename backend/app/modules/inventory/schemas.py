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
from app.modules.products.schemas import ProductCreate, ProductRead, ProductUnit

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
#: Corrections : les seules écritures de stock qui ne découlent d'aucun flux métier.
#: Elles exigent une raison (ADR 0067) et passent en audit critique.
CORRECTION_TYPES: frozenset[str] = frozenset({"adjustment", "loss"})

#: Raisons d'une correction, en liste fermée (révision 0015, ADR 0067).
type StockReason = Literal[
    "damaged", "expired", "lost_or_stolen", "home_use", "count_error", "found", "supplier_gift"
]
#: Raisons d'une perte (`loss`) : abîmé ou cassé, périmé, perdu ou volé, pris pour la
#: maison. Les autres sont des ajustements (`adjustment`).
LOSS_REASONS: frozenset[str] = frozenset({"damaged", "expired", "lost_or_stolen", "home_use"})
#: Raisons qui ne vont que dans un sens : un article retrouvé ou offert s'ajoute.
GAIN_REASONS: frozenset[str] = frozenset({"found", "supplier_gift"})


class MovementCreate(BaseModel):
    """Saisie d'un mouvement manuel."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    #: Omis avec une raison : déduit d'elle (`loss` ou `adjustment`, ADR 0067).
    type: ManualMovementType | None = None
    qty_delta: Quantity
    #: Obligatoire sur une réception, interdit sur une sortie (le trigger estampille
    #: le CMP), facultatif sur un ajustement positif (défaut : CMP courant, ADR 0016).
    unit_cost: MovementUnitCost | None = None
    supplier_id: UUID | None = None
    note: MovementNote | None = None
    #: Obligatoire sur une correction (`adjustment`, `loss`), interdite ailleurs.
    reason_code: StockReason | None = None
    #: Date métier. Par défaut `now()`. Bornée des deux côtés (ADR 0015) : 48 h
    #: d'antidatage au plus, et jamais dans le futur.
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def _check_coherence(self) -> Self:
        """Double les `CHECK` de la base, pour un refus qui nomme le champ."""
        if self.reason_code is not None:
            deduced: ManualMovementType = (
                "loss" if self.reason_code in LOSS_REASONS else "adjustment"
            )
            if self.type is not None and self.type != deduced:
                raise ValueError(
                    f"reason_code : la raison « {self.reason_code} » ne va pas avec "
                    f"un mouvement « {self.type} »."
                )
            self.type = deduced
            if self.reason_code in GAIN_REASONS and self.qty_delta < 0:
                raise ValueError(
                    f"reason_code : la raison « {self.reason_code} » ajoute au stock (> 0)."
                )
        if self.type is None:
            raise ValueError("type : indiquez le type du mouvement ou la raison.")
        if self.type in CORRECTION_TYPES and self.reason_code is None:
            raise ValueError(f"reason_code : une correction « {self.type} » exige une raison.")
        if self.qty_delta == 0:
            raise ValueError("qty_delta : un mouvement de zéro n'a aucun sens.")
        if self.type in POSITIVE_TYPES and self.qty_delta < 0:
            raise ValueError(f"qty_delta : un mouvement « {self.type} » est une entrée (> 0).")
        if self.type in NEGATIVE_TYPES and self.qty_delta > 0:
            raise ValueError(f"qty_delta : un mouvement « {self.type} » est une sortie (< 0).")
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

    @property
    def movement_type(self) -> ManualMovementType:
        """Le type, saisi ou déduit de la raison : jamais nul après validation."""
        if self.type is None:  # pragma: no cover - garanti par `_check_coherence`
            raise ValueError("type manquant")
        return self.type


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
    reason_code: StockReason | None
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
    #: L'unité de l'article (« Plus que 2 sacs », phase 15 lot 1) : ajout de lecture.
    unit: ProductUnit
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


class NewProductCreate(ProductCreate):
    """Un article et ce qu'on en a déjà (ADR 0066) : « Combien en avez-vous ? ».

    Inventory compose la façade de Products : l'article et son mouvement `initial`
    naissent dans la même transaction. Le stock d'ouverture est valorisé au prix d'achat.
    """

    opening_qty: Annotated[Quantity, Field(ge=Decimal("0"))] = Decimal("0")

    @model_validator(mode="after")
    def _opening_stock_has_a_cost(self) -> Self:
        if self.opening_qty > 0:
            if not self.is_stock_tracked:
                raise ValueError("opening_qty : un article sans suivi du stock n'a pas de stock.")
            if self.cost_price is None:
                raise ValueError("cost_price : le stock d'ouverture se valorise au prix d'achat.")
        return self

    def product(self) -> ProductCreate:
        """La fiche seule, telle que Products la reçoit."""
        return ProductCreate.model_validate(self.model_dump(exclude={"opening_qty"}))


class NewProductRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: ProductRead
    #: Le mouvement `initial`, ou rien si la quantité était nulle.
    opening_movement: MovementRead | None
