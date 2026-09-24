"""Schémas du module Products.

Les montants sont des `Decimal` en Python et des **chaînes** en JSON : les types
annotés de `app/core/money.py` s'en chargent. Aucun flottant ne traverse l'API.

`ProductRead` expose le prix courant, qui n'est pas une colonne de `products` mais
une **jointure** sur l'intervalle ouvert de `product_prices`. C'est ce que la
caisse et le catalogue affichent ; le stocker sur la fiche serait interdit.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.money import Amount, Quantity, Rate, UnitCost

if TYPE_CHECKING:  # pragma: no cover - uniquement pour le typage
    from app.modules.products.models import Product, ProductPrice

NAME_MAX_LENGTH = 200
SKU_MAX_LENGTH = 64
BARCODE_MAX_LENGTH = 64

#: Les 6 valeurs du `CHECK (unit IN (...))` du § 8.3, et rien d'autre.
type ProductUnit = Literal["piece", "kg", "litre", "carton", "metre", "paquet"]

type ProductName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH)
]
#: Le SKU est mis en majuscules : `products_sku_uq` est sensible à la casse, et
#: « riz-25 » puis « RIZ-25 » désigneraient deux produits pour le même article.
type Sku = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_upper=True, min_length=1, max_length=SKU_MAX_LENGTH
    ),
]
type Barcode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=BARCODE_MAX_LENGTH)
]

# Les bornes des `CHECK` du § 8.3, portées par le schéma : une valeur hors bornes
# sort en 422 avec le champ fautif, au lieu d'un 500 sur violation de contrainte.
# La base reste l'autorité — elle tient même si un jour un appel contourne l'API.
type TaxRate = Annotated[Rate, Field(ge=Decimal("0"), lt=Decimal("1"))]
type SellingPrice = Annotated[Amount, Field(gt=Decimal("0"))]
type CostPrice = Annotated[UnitCost, Field(ge=Decimal("0"))]
type ReorderPoint = Annotated[Quantity, Field(ge=Decimal("0"))]


class ProductRead(BaseModel):
    """Fiche produit, augmentée de son prix courant."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    category_id: UUID | None
    sku: str
    barcode: str | None
    name: str
    unit: ProductUnit
    is_stock_tracked: bool
    default_tax_rate: TaxRate
    reorder_point: ReorderPoint | None
    is_active: bool
    created_at: datetime
    #: Intervalle ouvert de `product_prices`. `null` signale un produit non tarifé,
    #: donc non vendable — un cas que la création rend impossible.
    unit_price: SellingPrice | None
    cost_price: CostPrice | None

    @classmethod
    def build(cls, product: Product, price: ProductPrice | None) -> ProductRead:
        """Assemble la fiche et son prix courant en une seule vue."""
        return cls(
            id=product.id,
            category_id=product.category_id,
            sku=product.sku,
            barcode=product.barcode,
            name=product.name,
            unit=product.unit,
            is_stock_tracked=product.is_stock_tracked,
            default_tax_rate=product.default_tax_rate,
            reorder_point=product.reorder_point,
            is_active=product.is_active,
            created_at=product.created_at,
            unit_price=None if price is None else price.unit_price,
            cost_price=None if price is None else price.cost_price,
        )


class ProductSummary(BaseModel):
    """Ce qu'un autre module a le droit de savoir d'un produit.

    Inventory s'en sert pour la vue « produits + stock » (ADR 0012) : il lit
    **ceci**, jamais le modèle `Product`. Pas de prix ici — le stock et le prix
    sont deux faits datés distincts.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    sku: str
    name: str
    category_id: UUID | None
    unit: ProductUnit
    is_stock_tracked: bool
    #: Taux **par défaut**, valeur de saisie. Sales le fige sur sa ligne à la
    #: confirmation et ne le relit jamais ensuite (§ 4.5).
    default_tax_rate: TaxRate
    reorder_point: ReorderPoint | None


class ProductCreate(BaseModel):
    """Création d'un produit **et** de son premier intervalle de prix.

    `unit_price` est obligatoire : un produit sans prix n'est pas vendable, et
    Sales n'aurait rien à figer sur sa ligne (ADR 0011).
    """

    model_config = ConfigDict(extra="forbid")

    sku: Sku
    name: ProductName
    unit: ProductUnit = "piece"
    barcode: Barcode | None = None
    category_id: UUID | None = None
    is_stock_tracked: bool = True
    default_tax_rate: TaxRate = Decimal("0")
    reorder_point: ReorderPoint | None = None
    unit_price: SellingPrice
    cost_price: CostPrice | None = None


class ProductUpdate(BaseModel):
    """Modification de la fiche. **Jamais** du prix : il a son propre endpoint."""

    model_config = ConfigDict(extra="forbid")

    sku: Sku | None = None
    name: ProductName | None = None
    unit: ProductUnit | None = None
    barcode: Barcode | None = None
    category_id: UUID | None = None
    is_stock_tracked: bool | None = None
    default_tax_rate: TaxRate | None = None
    reorder_point: ReorderPoint | None = None
    is_active: bool | None = None


class ProductPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProductRead]
    page: int
    page_size: int
    total: int


class ProductPriceRead(BaseModel):
    """Un intervalle de tarification. `valid_to = null` : c'est le prix courant."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    product_id: UUID
    unit_price: SellingPrice
    cost_price: CostPrice | None
    valid_from: datetime
    valid_to: datetime | None
    created_by: UUID | None


class ProductPriceCreate(BaseModel):
    """Nouveau prix. L'intervalle courant est fermé au même instant."""

    model_config = ConfigDict(extra="forbid")

    unit_price: SellingPrice
    cost_price: CostPrice | None = None


class ProductPricePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProductPriceRead]
    page: int
    page_size: int
    total: int


class CurrentPrice(BaseModel):
    """Prix courant, tel que les autres modules le reçoivent de la façade.

    Sales et Inventory lisent **ceci**, jamais le modèle `ProductPrice` : un module
    n'importe pas les modèles d'un autre (décision 01).
    """

    model_config = ConfigDict(extra="forbid")

    #: Identifiant de l'intervalle de `product_prices`. C'est lui que la ligne de
    #: vente conserve : une vente reste rattachable au tarif qui s'appliquait,
    #: même après plusieurs changements de prix (§ 5.1 étape 3).
    price_id: UUID
    product_id: UUID
    unit_price: SellingPrice
    cost_price: CostPrice | None
    valid_from: datetime
