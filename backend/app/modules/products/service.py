"""Façade de services du module Products.

Deux responsabilités distinctes vivent ici :

* le **CRUD** de la fiche produit et de son historique de prix ;
* la **façade** que Sales et Inventory utiliseront à partir de la phase 04 :
  `get_current_price`, `get_tax_rate`, `is_stock_tracked`, `assert_sellable`. Ces
  fonctions sont le seul point d'entrée des autres modules — jamais le repository,
  jamais les modèles (décision 01).

Products dépend de Categories, dans ce sens uniquement (Diagramme 3), et passe par
la façade `categories.service`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import BusinessRuleError, NotFoundError, sqlstate
from app.core.search import normalise_term
from app.core.tenancy import TenantContext
from app.modules.categories import service as categories_service
from app.modules.products.models import Product, ProductPrice
from app.modules.products.repository import ProductPriceRepository, ProductRepository
from app.modules.products.schemas import (
    CurrentPrice,
    ProductCreate,
    ProductPriceCreate,
    ProductUpdate,
)

# --------------------------------------------------------------- erreurs métier


class ProductSkuTakenError(BusinessRuleError):
    code = "product_sku_taken"
    default_message = "Un produit utilise déjà cette référence."


class ProductBarcodeTakenError(BusinessRuleError):
    code = "product_barcode_taken"
    default_message = "Un produit utilise déjà ce code-barres."


class ProductInactiveError(BusinessRuleError):
    code = "product_inactive"
    default_message = "Ce produit est désactivé : il ne peut pas être vendu."


class ProductNotPricedError(BusinessRuleError):
    code = "product_not_priced"
    default_message = "Ce produit n'a aucun prix en cours."


class PriceChangeConflictError(BusinessRuleError):
    code = "price_change_conflict"
    default_message = "Le prix vient d'être modifié ailleurs. Réessayez."


#: `exclusion_violation` — deux intervalles de prix qui se chevauchent. Ne peut
#: arriver que si deux changements de prix concurrents visent le même produit :
#: `product_prices_no_overlap` tranche, et le perdant reçoit un conflit lisible.
_EXCLUSION_VIOLATION = "23P01"


# ------------------------------------------------------------------- lectures


def list_products(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    category_id: UUID | None = None,
    is_active: bool | None = None,
) -> tuple[Sequence[tuple[Product, ProductPrice | None]], int]:
    """Page de produits, chacun accompagné de son prix courant."""
    repository = ProductRepository(session, ctx)
    term = normalise_term(search)
    products = repository.page_live(
        page=page, page_size=page_size, search=term, category_id=category_id, is_active=is_active
    )
    prices = ProductPriceRepository(session, ctx).current_by_product(
        [product.id for product in products]
    )
    total = repository.count_live(search=term, category_id=category_id, is_active=is_active)
    return [(product, prices.get(product.id)) for product in products], total


def get_product(session: Session, ctx: TenantContext, product_id: UUID) -> Product:
    """Produit du tenant courant. Celui d'une autre entreprise donne 404."""
    product = ProductRepository(session, ctx).get_live(product_id)
    if product is None:
        raise NotFoundError("Produit introuvable.")
    return product


def get_product_with_price(
    session: Session, ctx: TenantContext, product_id: UUID
) -> tuple[Product, ProductPrice | None]:
    """Fiche et intervalle de prix ouvert, tels que l'API les renvoie."""
    product = get_product(session, ctx, product_id)
    return product, ProductPriceRepository(session, ctx).current(product.id)


def list_prices(
    session: Session, ctx: TenantContext, product_id: UUID, *, page: int, page_size: int
) -> tuple[Sequence[ProductPrice], int]:
    """Historique de tarification, du plus récent au plus ancien."""
    product = get_product(session, ctx, product_id)
    repository = ProductPriceRepository(session, ctx)
    items = repository.page_for_product(product.id, page=page, page_size=page_size)
    return items, repository.count_for_product(product.id)


# ------------------------------------------------- façade des autres modules


def get_current_price(session: Session, ctx: TenantContext, product_id: UUID) -> CurrentPrice:
    """Prix en vigueur d'un produit, pour Sales.

    Lève `product_not_priced` plutôt que de renvoyer zéro : une vente à un prix
    inventé serait pire qu'une vente refusée.
    """
    product = get_product(session, ctx, product_id)
    price = ProductPriceRepository(session, ctx).current(product.id)
    if price is None:
        raise ProductNotPricedError(details={"product_id": str(product.id)})
    return CurrentPrice(
        product_id=product.id,
        unit_price=price.unit_price,
        cost_price=price.cost_price,
        valid_from=price.valid_from,
    )


def get_tax_rate(session: Session, ctx: TenantContext, product_id: UUID) -> Decimal:
    """Taux de taxe **par défaut** du produit.

    C'est une valeur de saisie : la ligne de vente la fige à la confirmation et ne
    la relit jamais (§ 4.2). Rien ici ne recalcule une vente passée.
    """
    return get_product(session, ctx, product_id).default_tax_rate


def is_stock_tracked(session: Session, ctx: TenantContext, product_id: UUID) -> bool:
    """Le produit suit-il un stock ? Inventory s'y réfère avant tout mouvement."""
    return get_product(session, ctx, product_id).is_stock_tracked


def assert_sellable(session: Session, ctx: TenantContext, product_id: UUID) -> CurrentPrice:
    """Vérifie qu'un produit peut être vendu, et renvoie le prix à appliquer.

    Trois refus possibles : introuvable (404), désactivé, sans prix en cours.
    """
    product = get_product(session, ctx, product_id)
    if not product.is_active:
        raise ProductInactiveError(details={"product_id": str(product.id)})
    return get_current_price(session, ctx, product.id)


def count_active_in_category(session: Session, ctx: TenantContext, category_id: UUID) -> int:
    """Nombre de produits actifs dans une catégorie."""
    return ProductRepository(session, ctx).count_live_in_category(category_id)


# ------------------------------------------------------------------- écritures


def _assert_codes_are_free(
    repository: ProductRepository,
    *,
    sku: str,
    barcode: str | None,
    excluding: UUID | None = None,
) -> None:
    """Unicité du SKU et du code-barres, pour un message lisible.

    Les contraintes `products_sku_uq` et `products_barcode_uq` restent l'autorité :
    en concurrence, c'est PostgreSQL qui tranche.
    """
    existing = repository.get_by_sku(sku)
    if existing is not None and existing.id != excluding:
        raise ProductSkuTakenError(details={"sku": sku})

    if barcode is not None:
        owner = repository.get_by_barcode(barcode)
        if owner is not None and owner.id != excluding:
            raise ProductBarcodeTakenError(details={"barcode": barcode})


def create_product(
    session: Session,
    ctx: TenantContext,
    payload: ProductCreate,
    *,
    ip_address: str | None = None,
) -> tuple[Product, ProductPrice]:
    """Crée la fiche **et** son premier intervalle de prix, en une transaction.

    Un produit sans prix n'existe donc jamais : `assert_sellable` n'a pas de cas
    dégradé à gérer, et Sales a toujours quelque chose à figer sur sa ligne.
    """
    repository = ProductRepository(session, ctx)
    if payload.category_id is not None:
        categories_service.assert_exists(session, ctx, payload.category_id)
    _assert_codes_are_free(repository, sku=payload.sku, barcode=payload.barcode)

    product = repository.add(
        Product(
            company_id=ctx.company_id,
            category_id=payload.category_id,
            sku=payload.sku,
            barcode=payload.barcode,
            name=payload.name,
            unit=payload.unit,
            is_stock_tracked=payload.is_stock_tracked,
            default_tax_rate=payload.default_tax_rate,
            reorder_point=payload.reorder_point,
            is_active=True,
        )
    )
    session.flush()

    price = ProductPriceRepository(session, ctx).add(
        ProductPrice(
            company_id=ctx.company_id,
            product_id=product.id,
            unit_price=payload.unit_price,
            cost_price=payload.cost_price,
            created_by=ctx.user_id,
        )
    )
    session.flush()

    # Le prix est une donnée financière : sa création est tracée comme ses
    # changements ultérieurs (ADR 0011).
    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT,
        entity_table="product_prices",
        entity_id=price.id,
        before=None,
        after={
            "product_id": str(product.id),
            "unit_price": price.unit_price,
            "cost_price": price.cost_price,
        },
        ip_address=ip_address,
    )
    return product, price


def update_product(
    session: Session,
    ctx: TenantContext,
    product_id: UUID,
    payload: ProductUpdate,
) -> tuple[Product, ProductPrice | None]:
    """Modifie la fiche. Le prix ne passe **jamais** par ici."""
    repository = ProductRepository(session, ctx)
    product = get_product(session, ctx, product_id)
    prices = ProductPriceRepository(session, ctx)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return product, prices.current(product.id)

    if "category_id" in changes and changes["category_id"] is not None:
        categories_service.assert_exists(session, ctx, changes["category_id"])
    if changes.keys() & {"sku", "barcode"}:
        _assert_codes_are_free(
            repository,
            sku=changes.get("sku", product.sku),
            barcode=changes.get("barcode", product.barcode),
            excluding=product.id,
        )

    for field, value in changes.items():
        setattr(product, field, value)
    session.flush()
    return product, prices.current(product.id)


def delete_product(
    session: Session,
    ctx: TenantContext,
    product_id: UUID,
    *,
    ip_address: str | None = None,
) -> tuple[Product, ProductPrice | None]:
    """Suppression **logique**, auditée : un produit vendu ne disparaît jamais.

    Le prix courant est lu **avant** la suppression : après, le produit n'est plus
    visible des lectures, et la réponse n'aurait plus de tarif à montrer.
    """
    product = get_product(session, ctx, product_id)
    price = ProductPriceRepository(session, ctx).current(product.id)

    before = {"is_active": product.is_active, "deleted_at": product.deleted_at}
    product.is_active = False
    product.deleted_at = datetime.now(UTC)
    session.flush()

    audit_critical(
        session,
        ctx,
        action=AuditAction.DELETE,
        entity_table="products",
        entity_id=product.id,
        before=before,
        after={"is_active": product.is_active, "deleted_at": product.deleted_at},
        ip_address=ip_address,
    )
    return product, price


def change_price(
    session: Session,
    ctx: TenantContext,
    product_id: UUID,
    payload: ProductPriceCreate,
    *,
    ip_address: str | None = None,
) -> ProductPrice:
    """Ferme l'intervalle courant et en ouvre un nouveau, dans **une** transaction.

    Les deux bornes valent `now()`, évalué par PostgreSQL : l'ancien prix s'arrête
    exactement là où le nouveau commence. Aucun trou, aucun recouvrement — et
    `product_prices_no_overlap` le garantit même en concurrence.
    """
    product = get_product(session, ctx, product_id)
    prices = ProductPriceRepository(session, ctx)
    # Retenu avant l'écriture : un rejet de `product_prices_no_overlap` annule la
    # transaction, et relire un attribut expiré échouerait à son tour.
    audited_product_id = str(product.id)

    previous = prices.current(product.id)
    before = (
        None
        if previous is None
        else {"unit_price": previous.unit_price, "cost_price": previous.cost_price}
    )
    prices.close_current(product.id)

    price = prices.add(
        ProductPrice(
            company_id=ctx.company_id,
            product_id=product.id,
            unit_price=payload.unit_price,
            cost_price=payload.cost_price,
            created_by=ctx.user_id,
        )
    )
    try:
        session.flush()
    except IntegrityError as exc:
        if sqlstate(exc) != _EXCLUSION_VIOLATION:
            raise
        raise PriceChangeConflictError(details={"product_id": audited_product_id}) from exc

    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="product_prices",
        entity_id=price.id,
        before=before,
        after={
            "product_id": audited_product_id,
            "unit_price": price.unit_price,
            "cost_price": price.cost_price,
        },
        ip_address=ip_address,
    )
    return price
