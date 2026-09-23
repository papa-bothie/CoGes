"""Requêtes du module Inventory — filtrées par tenant, sans règle métier.

Rien ici n'écrit `product_stock` : la projection est en lecture seule pour le code
applicatif, c'est le trigger `t20_inv_apply` qui la maintient (§ 5.6).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from app.core.repository import MAX_PAGE_SIZE, TenantRepository
from app.core.tenancy import TenantContext
from app.modules.inventory.models import InventoryMovement, ProductStock


def _check_page(page: int, page_size: int) -> None:
    """Pagination obligatoire sur toutes les listes (`CLAUDE.md` § 5)."""
    if page < 1:
        raise ValueError("page doit être >= 1")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size doit être entre 1 et {MAX_PAGE_SIZE}")


class InventoryMovementRepository(TenantRepository[InventoryMovement]):
    """Le journal, en lecture. Aucune méthode de modification : il est append-only."""

    model = InventoryMovement

    def _filters(
        self,
        *,
        product_id: UUID | None = None,
        movement_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if product_id is not None:
            filters.append(InventoryMovement.product_id == product_id)
        if movement_type is not None:
            filters.append(InventoryMovement.type == movement_type)
        if date_from is not None:
            filters.append(InventoryMovement.occurred_at >= date_from)
        if date_to is not None:
            filters.append(InventoryMovement.occurred_at <= date_to)
        return filters

    def page_filtered(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        product_id: UUID | None = None,
        movement_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Sequence[InventoryMovement]:
        """Journal du plus récent au plus ancien, `id` pour départager."""
        _check_page(page, page_size)
        stmt = (
            self._select()
            .where(
                *self._filters(
                    product_id=product_id,
                    movement_type=movement_type,
                    date_from=date_from,
                    date_to=date_to,
                )
            )
            .order_by(InventoryMovement.occurred_at.desc(), InventoryMovement.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def count_filtered(
        self,
        *,
        product_id: UUID | None = None,
        movement_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(InventoryMovement)
            .where(
                InventoryMovement.company_id == self.ctx.company_id,
                *self._filters(
                    product_id=product_id,
                    movement_type=movement_type,
                    date_from=date_from,
                    date_to=date_to,
                ),
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def reversal_of(self, movement_id: UUID) -> InventoryMovement | None:
        """Le mouvement qui annule celui-ci, s'il existe déjà.

        `inv_reversal_uq` reste l'autorité sous concurrence ; cette lecture sert à
        rendre `already_reversed` plutôt qu'un message de stock trompeur : le
        trigger `t20_inv_apply` se déclenche **avant** la contrainte d'unicité et
        refuserait d'abord la sortie si le stock ne suffit plus.
        """
        stmt = self._select().where(InventoryMovement.reversal_of_movement_id == movement_id)
        return self.session.execute(stmt).scalar_one_or_none()


class ProductStockRepository:
    """Projection de stock. `TenantRepository` ne convient pas : la clé est le produit.

    Le filtre `company_id` est donc répété explicitement dans chaque requête.
    """

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def _select(self) -> Select[tuple[ProductStock]]:
        return select(ProductStock).where(ProductStock.company_id == self.ctx.company_id)

    def get(self, product_id: UUID) -> ProductStock | None:
        stmt = self._select().where(ProductStock.product_id == product_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def many(self, product_ids: Sequence[UUID]) -> dict[UUID, ProductStock]:
        """Une requête pour une page entière, plutôt qu'une par ligne."""
        if not product_ids:
            return {}
        stmt = self._select().where(ProductStock.product_id.in_(product_ids))
        return {row.product_id: row for row in self.session.execute(stmt).scalars().all()}

    def page(self, *, page: int = 1, page_size: int = 20) -> Sequence[ProductStock]:
        _check_page(page, page_size)
        stmt = (
            self._select()
            .order_by(ProductStock.qty_on_hand.asc(), ProductStock.product_id.asc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def count(self) -> int:
        stmt = (
            select(func.count())
            .select_from(ProductStock)
            .where(ProductStock.company_id == self.ctx.company_id)
        )
        return int(self.session.execute(stmt).scalar_one())
