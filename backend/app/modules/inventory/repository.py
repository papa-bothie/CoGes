"""Requêtes du module Inventory — filtrées par tenant, sans règle métier.

Rien ici n'écrit `product_stock` : la projection est en lecture seule pour le code
applicatif, c'est le trigger `t20_inv_apply` qui la maintient (§ 5.6).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select, text
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

    def for_references(self, ref_type: str, ref_ids: Sequence[UUID]) -> Sequence[InventoryMovement]:
        """Mouvements **directs** rattachés à ces objets métier, les plus anciens d'abord.

        Les inverses sont écartés : `t10_inv_check_reversal` leur recopie le
        `ref_type` et le `ref_id` de leur origine, si bien qu'une sortie de vente et
        son annulation portent la même référence. Sans ce filtre, annuler une vente
        déjà annulée chercherait à inverser l'inverse. Sert l'index `inv_ref_lookup`.
        """
        if not ref_ids:
            return []
        stmt = (
            self._select()
            .where(
                InventoryMovement.ref_type == ref_type,
                InventoryMovement.ref_id.in_(ref_ids),
                InventoryMovement.reversal_of_movement_id.is_(None),
            )
            .order_by(InventoryMovement.occurred_at.asc(), InventoryMovement.id.asc())
        )
        return self.session.execute(stmt).scalars().all()


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


#: Stock moyen détenu sur une période, reconstitué depuis le journal (ADR 0033).
#:
#: Le stock est une projection des mouvements (décision 10) : la quantité détenue au
#: soir d'un jour passé n'est stockée nulle part, elle se rejoue. `base` donne l'état
#: à la veille du début, `mouvements` les variations de chaque jour, et la somme
#: cumulée fenêtrée reconstitue chaque fin de journée.
#:
#: Les jours sans mouvement doivent exister dans la série, sinon la moyenne est
#: biaisée : un article immobile pendant vingt jours puis écoulé en un jour aurait
#: sinon le même stock moyen qu'un article en rotation constante. D'où le
#: `generate_series` et le `CROSS JOIN`.
_AVERAGE_ON_HAND = text(
    """
    WITH jours AS (
         SELECT generate_series(CAST(:period_from AS date),
                                CAST(:period_to   AS date),
                                interval '1 day')::date AS day
    ),
    produits AS (
         SELECT unnest(CAST(:product_ids AS uuid[])) AS product_id
    ),
    base AS (
         SELECT m.product_id, SUM(m.qty_delta) AS qty
           FROM inventory_movements m
          WHERE m.company_id = :company_id
            AND m.product_id = ANY(CAST(:product_ids AS uuid[]))
            AND (m.occurred_at AT TIME ZONE :timezone)::date < CAST(:period_from AS date)
          GROUP BY m.product_id
    ),
    mouvements AS (
         SELECT m.product_id,
                (m.occurred_at AT TIME ZONE :timezone)::date AS day,
                SUM(m.qty_delta) AS delta
           FROM inventory_movements m
          WHERE m.company_id = :company_id
            AND m.product_id = ANY(CAST(:product_ids AS uuid[]))
            AND (m.occurred_at AT TIME ZONE :timezone)::date
                BETWEEN CAST(:period_from AS date) AND CAST(:period_to AS date)
          GROUP BY m.product_id, 2
    ),
    soirs AS (
         SELECT pr.product_id,
                COALESCE(b.qty, 0)
                  + COALESCE(SUM(mv.delta) OVER (PARTITION BY pr.product_id ORDER BY j.day), 0)
                  AS on_hand
           FROM jours j
           CROSS JOIN produits pr
           LEFT JOIN base b       ON b.product_id = pr.product_id
           LEFT JOIN mouvements mv ON mv.product_id = pr.product_id AND mv.day = j.day
    )
    SELECT product_id, AVG(on_hand) AS avg_on_hand
      FROM soirs
     GROUP BY product_id
    """
)


class StockHistoryRepository:
    """Lectures historiques du journal, pour la bande E."""

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def average_on_hand(
        self,
        *,
        product_ids: Sequence[UUID],
        period_from: date,
        period_to: date,
        timezone: str,
    ) -> dict[UUID, Decimal]:
        """Stock moyen de fin de journée, par produit, sur la période."""
        if not product_ids:
            return {}
        rows = self.session.execute(
            _AVERAGE_ON_HAND,
            {
                "company_id": self.ctx.company_id,
                "product_ids": list(dict.fromkeys(product_ids)),
                "period_from": period_from,
                "period_to": period_to,
                "timezone": timezone,
            },
        ).all()
        return {row.product_id: Decimal(row.avg_on_hand) for row in rows}
