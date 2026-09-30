"""Accès aux données du module Products : fiches et intervalles de prix.

Requêtes filtrées par tenant, et rien d'autre. Les deux tables appartiennent au
même module : `product_prices` n'existe que pour `products`.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, or_, select, update

from app.core.repository import TenantRepository
from app.core.search import code_matches, name_matches, relevance_order
from app.modules.products.models import Product, ProductPrice


class ProductRepository(TenantRepository[Product]):
    """Hérite du filtre tenant : aucune requête ne peut s'en passer."""

    model = Product

    def _live(self) -> Select[tuple[Product]]:
        return self._select().where(Product.deleted_at.is_(None))

    def _filters(
        self, *, search: str | None, category_id: UUID | None, is_active: bool | None
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if search is not None:
            # Le nom par approximation, les codes par égalité stricte : un
            # code-barres scanné ne doit jamais ramener « le plus ressemblant ».
            conditions.append(
                or_(
                    name_matches(Product.name, search),
                    code_matches((Product.sku, Product.barcode), search),
                )
            )
        if category_id is not None:
            conditions.append(Product.category_id == category_id)
        if is_active is not None:
            conditions.append(Product.is_active.is_(is_active))
        return conditions

    def get_live(self, product_id: UUID) -> Product | None:
        return self.session.execute(
            self._live().where(Product.id == product_id)
        ).scalar_one_or_none()

    def live_by_ids(self, product_ids: Sequence[UUID]) -> dict[UUID, Product]:
        """Fiches vivantes d'une page d'identifiants, en une requête (pas de N+1).

        Sert la façade `get_summaries`, par laquelle Inventory joint le stock aux
        fiches produit sans jamais toucher à ce modèle (ADR 0012).
        """
        if not product_ids:
            return {}
        stmt = self._live().where(Product.id.in_(product_ids))
        return {product.id: product for product in self.session.execute(stmt).scalars()}

    def active_ids(self) -> list[UUID]:
        """Identifiants des produits vivants et actifs, dans un ordre stable."""
        stmt = self._live().where(Product.is_active.is_(True)).order_by(Product.id)
        return list(self.session.execute(stmt.with_only_columns(Product.id)).scalars())

    def reorder_points(self) -> dict[UUID, Decimal]:
        """Seuils d'alerte des produits suivis en stock qui en ont un.

        Les produits sans seuil sont absents : ils ne peuvent pas déclencher d'alerte,
        et les faire remonter pour les écarter ensuite serait lire pour rien.
        """
        stmt = self._live().where(
            Product.reorder_point.is_not(None),
            Product.is_stock_tracked.is_(True),
            Product.is_active.is_(True),
        )
        rows = self.session.execute(stmt.with_only_columns(Product.id, Product.reorder_point)).all()
        return {row[0]: row[1] for row in rows}

    def get_by_sku(self, sku: str) -> Product | None:
        """Homonyme de SKU, **y compris supprimé**.

        `products_sku_uq` n'est pas restreinte aux lignes vivantes : un SKU reste
        réservé après une suppression logique. Le contrôle doit donc voir les
        lignes supprimées, sinon le message serait « SKU libre » puis 500.
        """
        return self.session.execute(self._select().where(Product.sku == sku)).scalar_one_or_none()

    def get_by_barcode(self, barcode: str) -> Product | None:
        """Homonyme de code-barres vivant (`products_barcode_uq` est partielle)."""
        return self.session.execute(
            self._live().where(Product.barcode == barcode)
        ).scalar_one_or_none()

    def count_live(
        self,
        *,
        search: str | None = None,
        category_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Product)
            .where(Product.company_id == self.ctx.company_id, Product.deleted_at.is_(None))
            .where(*self._filters(search=search, category_id=category_id, is_active=is_active))
        )
        return int(self.session.execute(stmt).scalar_one())

    def page_live(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        category_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> Sequence[Product]:
        stmt = (
            self._live()
            .where(*self._filters(search=search, category_id=category_id, is_active=is_active))
            .order_by(*relevance_order(Product.name, (Product.sku, Product.barcode), search))
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def count_live_in_category(self, category_id: UUID) -> int:
        """Produits actifs rattachés à une catégorie.

        Sert à Products seul ; la garde de suppression d'une catégorie, elle, est
        en base (trigger `categories_guard_soft_delete`), parce que `Categories`
        ne dépend d'aucun module.
        """
        stmt = (
            select(func.count())
            .select_from(Product)
            .where(
                Product.company_id == self.ctx.company_id,
                Product.category_id == category_id,
                Product.deleted_at.is_(None),
                Product.is_active.is_(True),
            )
        )
        return int(self.session.execute(stmt).scalar_one())


class ProductPriceRepository(TenantRepository[ProductPrice]):
    """Historique de tarification. Une ligne ne se corrige pas : elle se ferme."""

    model = ProductPrice

    def current(self, product_id: UUID) -> ProductPrice | None:
        """Intervalle ouvert (`valid_to IS NULL`), servi par l'index `prices_current`."""
        stmt = self._select().where(
            ProductPrice.product_id == product_id, ProductPrice.valid_to.is_(None)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def current_by_product(self, product_ids: Sequence[UUID]) -> dict[UUID, ProductPrice]:
        """Prix courants d'une page de produits, en une requête (pas de N+1)."""
        if not product_ids:
            return {}
        stmt = self._select().where(
            ProductPrice.product_id.in_(product_ids), ProductPrice.valid_to.is_(None)
        )
        return {price.product_id: price for price in self.session.execute(stmt).scalars()}

    def close_current(self, product_id: UUID) -> None:
        """Ferme l'intervalle ouvert à `now()` — l'instant de la transaction.

        `now()` est évalué **par PostgreSQL** et vaut le début de la transaction :
        le nouvel intervalle, ouvert dans la même transaction, commence donc
        exactement là où l'ancien s'arrête, sans trou ni recouvrement, et sans
        dépendre de l'horloge du serveur d'application.
        """
        stmt = (
            update(ProductPrice)
            .where(
                ProductPrice.company_id == self.ctx.company_id,
                ProductPrice.product_id == product_id,
                ProductPrice.valid_to.is_(None),
            )
            .values(valid_to=func.now())
        )
        self.session.execute(stmt)

    def count_for_product(self, product_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ProductPrice)
            .where(
                ProductPrice.company_id == self.ctx.company_id,
                ProductPrice.product_id == product_id,
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def page_for_product(
        self, product_id: UUID, *, page: int, page_size: int
    ) -> Sequence[ProductPrice]:
        """Historique du plus récent au plus ancien (index `prices_history`)."""
        stmt = (
            self._select()
            .where(ProductPrice.product_id == product_id)
            .order_by(ProductPrice.valid_from.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()
