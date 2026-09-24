"""Requêtes du module Sales — filtrées par tenant, sans règle métier."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, text

from app.core.repository import MAX_PAGE_SIZE, TenantRepository
from app.modules.sales.models import Sale, SaleItem

#: Les ventes n'ont pas de suppression logique : une vente ne s'efface pas, elle
#: s'annule. `sales` ne porte donc aucune colonne `deleted_at`.

_COUNT_RETURNS = text(
    """
    SELECT sale_id, count(*) AS n FROM sale_returns
     WHERE company_id = :company_id AND sale_id = ANY(:sale_ids)
     GROUP BY sale_id
    """
)


class SaleRepository(TenantRepository[Sale]):
    """En-têtes de vente. Les totaux sont lus, jamais écrits (triggers du § 8.7)."""

    model = Sale

    def get_for_update(self, sale_id: UUID) -> Sale | None:
        """Verrouille la vente pour la durée de la transaction (§ 5.1 étape 1).

        Deux caisses qui confirment la même vente sont ainsi sérialisées : la
        seconde relit `status = 'confirmed'` et se fait refuser proprement.
        """
        stmt = self._select().where(Sale.id == sale_id).with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def _filters(
        self,
        *,
        status: str | None = None,
        customer_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sale_no: str | None = None,
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if status is not None:
            filters.append(Sale.status == status)
        if customer_id is not None:
            filters.append(Sale.customer_id == customer_id)
        if date_from is not None:
            filters.append(Sale.sold_at >= date_from)
        if date_to is not None:
            filters.append(Sale.sold_at <= date_to)
        if sale_no is not None:
            # Égalité stricte sur un numéro, jamais de `LIKE` : un numéro se lit,
            # se dicte et se retrouve entier (ADR 0013).
            filters.append(Sale.sale_no == sale_no)
        return filters

    def page_filtered(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        customer_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sale_no: str | None = None,
    ) -> Sequence[Sale]:
        """Ventes de la plus récente à la plus ancienne, `id` pour départager."""
        if page < 1:
            raise ValueError("page doit être >= 1")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size doit être entre 1 et {MAX_PAGE_SIZE}")
        stmt = (
            self._select()
            .where(
                *self._filters(
                    status=status,
                    customer_id=customer_id,
                    date_from=date_from,
                    date_to=date_to,
                    sale_no=sale_no,
                )
            )
            .order_by(Sale.sold_at.desc(), Sale.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def count_filtered(
        self,
        *,
        status: str | None = None,
        customer_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sale_no: str | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Sale)
            .where(
                Sale.company_id == self.ctx.company_id,
                *self._filters(
                    status=status,
                    customer_id=customer_id,
                    date_from=date_from,
                    date_to=date_to,
                    sale_no=sale_no,
                ),
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def with_returns(self, sale_ids: Sequence[UUID]) -> set[UUID]:
        """Parmi ces ventes, celles qui portent au moins un retour.

        Requête en SQL direct plutôt que par un modèle : `sale_returns` appartient
        bien au module Sales, mais son modèle et son service arrivent en phase 06.
        Déclarer la table à moitié laisserait croire qu'on peut déjà l'écrire.
        Une seule requête pour une page entière, jamais une par ligne.
        """
        if not sale_ids:
            return set()
        rows = self.session.execute(
            _COUNT_RETURNS,
            {"company_id": self.ctx.company_id, "sale_ids": list(sale_ids)},
        ).all()
        return {row.sale_id for row in rows}


class SaleItemRepository(TenantRepository[SaleItem]):
    """Lignes de vente. Figées par `sale_items_no_change` dès la confirmation."""

    model = SaleItem

    def for_sale(self, sale_id: UUID) -> Sequence[SaleItem]:
        """Lignes d'une vente, dans l'ordre de saisie."""
        stmt = (
            self._select()
            .where(SaleItem.sale_id == sale_id)
            .order_by(SaleItem.created_at.asc(), SaleItem.id.asc())
        )
        return self.session.execute(stmt).scalars().all()

    def for_sale_ordered_by_product(self, sale_id: UUID) -> Sequence[SaleItem]:
        """Lignes d'une vente triées par `product_id` croissant.

        L'ordre n'est pas cosmétique : c'est lui qui élimine les interblocages
        entre deux caisses vendant les deux mêmes articles (§ 5). Le verrou sur
        `product_stock` est posé par `t20_inv_apply` au moment de l'insertion du
        mouvement, donc dans l'ordre où les lignes sont parcourues ici.
        """
        stmt = (
            self._select()
            .where(SaleItem.sale_id == sale_id)
            .order_by(SaleItem.product_id.asc(), SaleItem.id.asc())
        )
        return self.session.execute(stmt).scalars().all()

    def get_in_sale(self, sale_id: UUID, item_id: UUID) -> SaleItem | None:
        """Ligne d'une vente précise : une ligne d'une autre vente donne 404."""
        stmt = self._select().where(SaleItem.sale_id == sale_id, SaleItem.id == item_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def count_for_sale(self, sale_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(SaleItem)
            .where(SaleItem.company_id == self.ctx.company_id, SaleItem.sale_id == sale_id)
        )
        return int(self.session.execute(stmt).scalar_one())

    def remove(self, item: SaleItem) -> None:
        """Retire une ligne de brouillon.

        Seule suppression physique du domaine métier, et seule exception au « pas
        de DELETE » en dehors du RBAC (ADR 0020). Elle n'est pas un choix de
        confort : `sale_items` n'a ni `deleted_at`, ni place pour une ligne
        neutralisée dans `sale_recompute_totals`, et `CHECK (qty > 0)` interdit de
        la vider. `sale_items_no_change` borne ce droit à la vie du brouillon.
        """
        self.session.delete(item)
