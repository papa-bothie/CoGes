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

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core import cloudinary, queue
from app.core.audit import AuditAction, audit_critical
from app.core.codes import CODE_ATTEMPTS, format_code, internal_ean13
from app.core.config import get_settings
from app.core.errors import (
    BusinessRuleError,
    CogesError,
    NotFoundError,
    PermissionDeniedError,
    constraint_name,
    sqlstate,
)
from app.core.search import normalise_term
from app.core.tenancy import TenantContext, on_commit
from app.modules.categories import service as categories_service
from app.modules.companies import service as companies_service
from app.modules.products.models import Product, ProductPrice
from app.modules.products.photo import (
    MAX_PHOTO_UPLOAD_BYTES,
    PhotoUnsupportedFormatError,
    normalize_photo,
)
from app.modules.products.repository import ProductPriceRepository, ProductRepository
from app.modules.products.schemas import (
    CurrentPrice,
    PhotoConfig,
    ProductCreate,
    ProductPriceCreate,
    ProductRead,
    ProductSummary,
    ProductUpdate,
    photo_of,
)

#: Préfixe des références attribuées par le serveur : `ART-0001` (ADR 0066).
SKU_PREFIX = "ART"

_UNIQUE_VIOLATION = "23505"

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
        price_id=price.id,
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


def get_summaries(
    session: Session,
    ctx: TenantContext,
    product_ids: Sequence[UUID],
    *,
    include_deleted: bool = False,
) -> dict[UUID, ProductSummary]:
    """Fiches résumées d'un lot de produits, pour Inventory.

    Renvoie un dictionnaire, et non une liste : l'appelant a déjà ses identifiants
    et veut les rattacher. Un produit supprimé est absent du résultat, sauf
    `include_deleted` : un retour sur un article supprimé depuis la vente doit encore
    savoir s'il remet la marchandise en stock (ADR 0088).
    """
    repository = ProductRepository(session, ctx)
    products = (
        repository.by_ids_including_deleted(product_ids)
        if include_deleted
        else repository.live_by_ids(product_ids)
    )
    return {product_id: _summary(product) for product_id, product in products.items()}


def _summary(product: Product) -> ProductSummary:
    return ProductSummary(
        id=product.id,
        sku=product.sku,
        barcode=product.barcode,
        name=product.name,
        description=product.description,
        category_id=product.category_id,
        unit=product.unit,
        is_stock_tracked=product.is_stock_tracked,
        default_tax_rate=product.default_tax_rate,
        reorder_point=product.reorder_point,
        photo=photo_of(product),
    )


def find_by_code(
    session: Session, ctx: TenantContext, codes: Sequence[str]
) -> ProductSummary | None:
    """L'article vivant qui porte exactement l'un de ces codes (ADR 0106).

    `codes` vient de `scanned_code_candidates`, la forme lue en tête. Le code-barres
    passe avant la référence, et la forme lue avant ses équivalents (UPC-A, EAN-13) :
    un code ne désigne jamais « le plus ressemblant ».
    """
    matches = ProductRepository(session, ctx).by_codes(codes, deleted=False)
    if not matches:
        return None

    def rank(product: Product) -> tuple[int, int]:
        if product.barcode in codes:
            return (0, codes.index(product.barcode))
        return (1, codes.index(product.sku))

    return _summary(min(matches, key=rank))


def code_was_deleted(session: Session, ctx: TenantContext, codes: Sequence[str]) -> bool:
    """Un article supprimé portait-il ce code ? L'écran le dit, au lieu de proposer un doublon."""
    return bool(ProductRepository(session, ctx).by_codes(codes, deleted=True))


def active_summaries(session: Session, ctx: TenantContext) -> dict[UUID, ProductSummary]:
    """Fiches résumées de tous les produits actifs, pour le pipeline d'Intelligence.

    Un produit archivé ou désactivé ne reçoit plus de prévision : on ne réapprovisionne
    pas ce qu'on ne vend plus.
    """
    return get_summaries(session, ctx, ProductRepository(session, ctx).active_ids())


def reorder_points(session: Session, ctx: TenantContext) -> dict[UUID, Decimal]:
    """Seuils d'alerte de l'entreprise, par produit.

    Façade pour Inventory, qui possède `product_stock` mais pas `products` : le
    comptage des alertes de stock compose les deux façades plutôt que de joindre la
    table d'un autre module (décision 01).
    """
    return ProductRepository(session, ctx).reorder_points()


def counts_by_category(session: Session, ctx: TenantContext) -> dict[UUID, int]:
    """Nombre d'articles de chaque rayon (écran 12, ADR 0071)."""
    return ProductRepository(session, ctx).counts_by_category()


def ids_matching(session: Session, ctx: TenantContext, search: str) -> list[UUID] | None:
    """Articles qui répondent à une recherche ; `None` si le terme est trop court."""
    term = normalise_term(search)
    if term is None:
        return None
    return ProductRepository(session, ctx).ids_matching(term)


def current_unit_prices(
    session: Session, ctx: TenantContext, product_ids: Sequence[UUID]
) -> dict[UUID, Decimal]:
    """Prix de vente courant de chaque article du lot (liste du stock, ADR 0071)."""
    prices = ProductPriceRepository(session, ctx).current_by_product(list(product_ids))
    return {product_id: price.unit_price for product_id, price in prices.items()}


def count_active_in_category(session: Session, ctx: TenantContext, category_id: UUID) -> int:
    """Nombre de produits actifs dans une catégorie."""
    return ProductRepository(session, ctx).count_live_in_category(category_id)


# ------------------------------------------------------------------- écritures


def _assert_codes_are_free(
    repository: ProductRepository,
    *,
    sku: str | None,
    barcode: str | None,
    excluding: UUID | None = None,
) -> None:
    """Unicité du SKU et du code-barres, pour un message lisible.

    Les contraintes `products_sku_uq` et `products_barcode_uq` restent l'autorité :
    en concurrence, c'est PostgreSQL qui tranche.
    """
    if sku is not None:
        existing = repository.get_by_sku(sku)
        if existing is not None and existing.id != excluding:
            raise ProductSkuTakenError(details={"sku": sku})

    if barcode is not None:
        owner = repository.get_by_barcode(barcode)
        if owner is not None and owner.id != excluding:
            raise ProductBarcodeTakenError(details={"barcode": barcode})


def _add_with_codes(
    session: Session,
    ctx: TenantContext,
    repository: ProductRepository,
    payload: ProductCreate,
    reorder_point: Decimal | None,
    tax_rate: Decimal,
) -> Product:
    """Ajoute la fiche avec sa référence et son code-barres, attribués s'ils manquent.

    Comme les codes clients (ADR 0013) : le numéro suivant vient du plus grand compteur
    de l'entreprise, et l'unicité de la base. Deux créations simultanées visent le même
    numéro ; `products_sku_uq` ou `products_barcode_uq` refuse la seconde, qui recommence
    sous un savepoint (ADR 0066).
    """
    for attempt in range(CODE_ATTEMPTS):
        sku = payload.sku or format_code(SKU_PREFIX, repository.max_sku_number(SKU_PREFIX) + 1)
        barcode = payload.barcode or internal_ean13(repository.max_internal_barcode_number() + 1)
        savepoint = session.begin_nested()
        product = repository.add(
            Product(
                company_id=ctx.company_id,
                category_id=payload.category_id,
                sku=sku,
                barcode=barcode,
                name=payload.name,
                description=payload.description,
                unit=payload.unit,
                is_stock_tracked=payload.is_stock_tracked,
                default_tax_rate=tax_rate,
                reorder_point=reorder_point,
                is_active=True,
            )
        )
        try:
            session.flush()
        except IntegrityError as exc:
            savepoint.rollback()
            if sqlstate(exc) != _UNIQUE_VIOLATION:
                raise
            # Un code imposé par l'appelant ne se corrige pas tout seul.
            constraint = constraint_name(exc)
            if constraint == "products_sku_uq" and payload.sku is not None:
                raise ProductSkuTakenError(details={"sku": sku}) from exc
            if constraint == "products_barcode_uq" and payload.barcode is not None:
                raise ProductBarcodeTakenError(details={"barcode": barcode}) from exc
            if attempt == CODE_ATTEMPTS - 1:
                raise ProductSkuTakenError(details={"sku": sku}) from exc
            continue
        savepoint.commit()
        return product
    raise AssertionError("boucle de numérotation sortie sans résultat")  # pragma: no cover


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

    # Seuil par défaut de l'entreprise pour un produit suivi saisi sans seuil (ADR 0054) :
    # appliqué ici, donc aussi à l'import CSV. Un seuil saisi, même 0, n'est pas remplacé.
    reorder_point = payload.reorder_point
    if reorder_point is None and payload.is_stock_tracked:
        reorder_point = companies_service.default_reorder_point(session, ctx)

    tax_rate = payload.default_tax_rate
    if tax_rate is None:
        tax_rate = companies_service.default_tax_rate(session, ctx)

    product = _add_with_codes(session, ctx, repository, payload, reorder_point, tax_rate)

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


class StockTrackingLockedError(BusinessRuleError):
    """`CG003` (révision 0025, ADR 0088)."""

    code = "stock_tracking_locked"
    default_message = (
        "Cet article a déjà des mouvements de stock : on ne peut plus changer s'il est "
        "suivi en stock."
    )


class ProductHasStockError(BusinessRuleError):
    """`CG004` (révision 0025, ADR 0088)."""

    code = "product_has_stock"
    default_message = (
        "Cet article a encore du stock : corrigez le stock à zéro avant de le supprimer."
    )


_GUARD_ERRORS: dict[str, type[BusinessRuleError]] = {
    "CG003": StockTrackingLockedError,
    "CG004": ProductHasStockError,
}


def _flush_guarded(session: Session, product: Product) -> None:
    """`flush` qui traduit les refus de `products_guard_stock` (ADR 0014, 0088).

    L'identifiant est lu **avant** : après un refus, la transaction est morte et relire
    un attribut expiré échouerait à son tour (ADR 0010).
    """
    details = {"product_id": str(product.id)}
    try:
        session.flush()
    except DBAPIError as exc:
        error = _GUARD_ERRORS.get(sqlstate(exc) or "")
        if error is None:
            raise
        raise error(details=details) from exc


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
    _flush_guarded(session, product)
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
    # L'image part avec l'article : supprimée chez Cloudinary après le COMMIT (ADR 0121).
    _drop_photo_after_commit(session, ctx, product)
    _flush_guarded(session, product)

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


# --------------------------------------------------------------- photos (ADR 0121)

#: Tâche du worker qui supprime une image chez Cloudinary, après le COMMIT.
DELETE_PHOTO_TASK = "products.delete_photo"
#: Une image de moins d'un jour n'est jamais balayée : son article est peut-être en train
#: de la recevoir (dépôt fait, COMMIT pas encore).
SWEEP_GRACE = timedelta(hours=24)


class PhotoUnavailableError(BusinessRuleError):
    code = "photo_unavailable"
    default_message = "Les photos des articles ne sont pas disponibles."


class PhotoNotFoundError(NotFoundError):
    code = "photo_not_found"
    default_message = "Cet article n'a pas de photo."


class PhotoStorageError(CogesError):
    code = "photo_storage_unavailable"
    status_code = 503
    default_message = "La photo n'a pas pu être enregistrée. Réessayez dans un instant."


#: Lu au plus depuis l'envoi : un octet de plus que la limite, pour la reconnaître.
MAX_PHOTO_READ_BYTES = MAX_PHOTO_UPLOAD_BYTES + 1


def read_product(session: Session, ctx: TenantContext, product: Product) -> ProductRead:
    """La fiche telle que l'API la rend, avec son prix courant."""
    return ProductRead.build(product, ProductPriceRepository(session, ctx).current(product.id))


def photo_config() -> PhotoConfig:
    return PhotoConfig(enabled=get_settings().photos_enabled)


def cloudinary_account() -> cloudinary.CloudinaryAccount | None:
    """Le compte du propriétaire, ou `None` : photos indisponibles, sans erreur."""
    settings = get_settings()
    if (
        settings.cloudinary_cloud_name is None
        or settings.cloudinary_api_key is None
        or settings.cloudinary_api_secret is None
    ):
        return None
    return cloudinary.CloudinaryAccount(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret.get_secret_value(),
        api_base=settings.cloudinary_api_base,
    )


def photo_folder(company_id: UUID) -> str:
    """Dossier d'une entreprise : par environnement, la préprod ne touche pas la prod."""
    return f"coges-{get_settings().env}/{company_id}"


def http_client() -> httpx.Client:
    """Client HTTP vers Cloudinary ; remplacé par un faux dans les tests."""
    return httpx.Client(timeout=get_settings().cloudinary_timeout_seconds)


def _photo_state(product: Product) -> dict[str, Any]:
    return {
        "photo_public_id": product.photo_public_id,
        "photo_version": product.photo_version,
        "photo_width": product.photo_width,
        "photo_height": product.photo_height,
    }


def _drop_photo_after_commit(session: Session, ctx: TenantContext, product: Product) -> None:
    """Vide les colonnes de la photo et fait supprimer l'image une fois le COMMIT passé."""
    old = product.photo_public_id
    if old is None:
        return
    product.photo_public_id = None
    product.photo_version = None
    product.photo_width = None
    product.photo_height = None
    company_id = str(ctx.company_id)

    def _enqueue() -> None:
        # Sans Redis, l'image reste orpheline : le balayage de nuit la retrouvera.
        queue.enqueue(DELETE_PHOTO_TASK, company_id=company_id, public_id=old)

    on_commit(session, _enqueue)


def may_set_photo(ctx: TenantContext, product: Product) -> bool:
    """`products:update`, ou `products:create` pour un article encore sans photo."""
    if ctx.has_permission("products:update"):
        return True
    return ctx.has_permission("products:create") and product.photo_public_id is None


def set_photo(
    session: Session,
    ctx: TenantContext,
    product_id: UUID,
    content: bytes | None,
    *,
    ip_address: str | None = None,
) -> Product:
    """Ajoute ou change la photo : vérifiée, ré-encodée, déposée, puis écrite en base.

    Le dépôt précède l'écriture : si la transaction échoue ensuite, l'image déposée n'est
    nommée par aucun article, et le balayage de nuit la supprime.
    """
    # L'article d'abord : celui d'une autre entreprise est introuvable, quoi qu'on envoie.
    product = get_product(session, ctx, product_id)
    account = cloudinary_account()
    if account is None:
        raise PhotoUnavailableError()
    if not may_set_photo(ctx, product):
        raise PermissionDeniedError()
    if not content:
        raise PhotoUnsupportedFormatError()
    photo = normalize_photo(content)

    public_id = f"{photo_folder(ctx.company_id)}/{secrets.token_urlsafe(16)}"
    try:
        with http_client() as client:
            uploaded = cloudinary.upload(account, photo.jpeg, public_id=public_id, client=client)
    except cloudinary.CloudinaryError as exc:
        raise PhotoStorageError() from exc

    before = _photo_state(product)
    _drop_photo_after_commit(session, ctx, product)
    product.photo_public_id = uploaded.public_id
    product.photo_version = uploaded.version
    product.photo_width = photo.width
    product.photo_height = photo.height
    _flush_guarded(session, product)
    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="products",
        entity_id=product.id,
        before=before,
        after={
            **_photo_state(product),
            "photo": "added" if before["photo_public_id"] is None else "changed",
        },
        ip_address=ip_address,
    )
    return product


def remove_photo(
    session: Session, ctx: TenantContext, product_id: UUID, *, ip_address: str | None = None
) -> Product:
    """Retire la photo : colonnes vidées, image supprimée chez Cloudinary après le COMMIT."""
    product = get_product(session, ctx, product_id)
    if product.photo_public_id is None:
        raise PhotoNotFoundError()
    before = _photo_state(product)
    _drop_photo_after_commit(session, ctx, product)
    _flush_guarded(session, product)
    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="products",
        entity_id=product.id,
        before=before,
        after={**_photo_state(product), "photo": "removed"},
        ip_address=ip_address,
    )
    return product


def delete_stored_photo(public_id: str) -> None:
    """Supprime une image chez Cloudinary (tâche du worker). Lève si Cloudinary échoue."""
    account = cloudinary_account()
    if account is None:
        return
    with http_client() as client:
        cloudinary.destroy(account, public_id, client=client)


def referenced_photos(session: Session, ctx: TenantContext) -> set[str]:
    """Images nommées par un article de l'entreprise, supprimé ou non."""
    return ProductRepository(session, ctx).photo_public_ids()


def orphan_photos(
    stored: Sequence[cloudinary.StoredImage], referenced: set[str], *, now: datetime
) -> list[str]:
    """Images du dossier qu'aucun article ne nomme, déposées depuis plus d'un jour."""
    return [
        image.public_id
        for image in stored
        if image.public_id not in referenced and now - image.created_at > SWEEP_GRACE
    ]
