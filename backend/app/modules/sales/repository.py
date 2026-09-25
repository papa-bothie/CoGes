"""Requêtes du module Sales — filtrées par tenant, sans règle métier."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, func, select

from app.core.repository import MAX_PAGE_SIZE, TenantRepository
from app.modules.sales.models import Sale, SaleItem, SaleReturn, SaleReturnItem

#: Les ventes n'ont pas de suppression logique : une vente ne s'efface pas, elle
#: s'annule. `sales` ne porte donc aucune colonne `deleted_at`. Un retour non plus :
#: il ne s'annule pas, il se corrige par un second retour (§ 4.6).


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

        Une seule requête pour une page entière, jamais une par ligne.
        """
        if not sale_ids:
            return set()
        stmt = (
            select(SaleReturn.sale_id)
            .where(
                SaleReturn.company_id == self.ctx.company_id,
                SaleReturn.sale_id.in_(sale_ids),
            )
            .group_by(SaleReturn.sale_id)
        )
        return set(self.session.execute(stmt).scalars().all())

    def returned_totals(self, sale_ids: Sequence[UUID]) -> dict[UUID, Decimal]:
        """Total remboursable retourné, par vente.

        Le statut « retournée » d'une vente est **dérivé** : aucune colonne ne le
        porte, et aucune ne le portera. Ce qui existe, ce sont des retours.
        """
        if not sale_ids:
            return {}
        stmt = (
            select(SaleReturn.sale_id, func.sum(SaleReturn.total_refund))
            .where(
                SaleReturn.company_id == self.ctx.company_id,
                SaleReturn.sale_id.in_(sale_ids),
            )
            .group_by(SaleReturn.sale_id)
        )
        return {sale_id: Decimal(total) for sale_id, total in self.session.execute(stmt).all()}


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


class SaleReturnRepository(TenantRepository[SaleReturn]):
    """En-têtes de retour. `total_refund`, `refunded_total` et `refund_status` sont
    maintenus par trigger : lus ici, jamais écrits."""

    model = SaleReturn

    def get_for_update(self, return_id: UUID) -> SaleReturn | None:
        """Verrouille le retour avant d'en calculer le reste dû (§ 5.4 étape 1).

        Sans ce verrou, deux remboursements concurrents liraient le même
        `refunded_total` et conclueraient tous deux qu'il reste de quoi payer.
        """
        stmt = self._select().where(SaleReturn.id == return_id).with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def for_sale(self, sale_id: UUID) -> Sequence[SaleReturn]:
        """Retours d'une vente, du plus récent au plus ancien."""
        stmt = (
            self._select()
            .where(SaleReturn.sale_id == sale_id)
            .order_by(SaleReturn.returned_at.desc(), SaleReturn.id.desc())
        )
        return self.session.execute(stmt).scalars().all()


class SaleReturnItemRepository(TenantRepository[SaleReturnItem]):
    """Lignes de retour. Le cumul par ligne de vente est borné par `sri_check`."""

    model = SaleReturnItem

    def for_return(self, return_id: UUID) -> Sequence[SaleReturnItem]:
        """Lignes d'un retour, dans l'ordre d'enregistrement."""
        stmt = (
            self._select()
            .where(SaleReturnItem.return_id == return_id)
            .order_by(SaleReturnItem.created_at.asc(), SaleReturnItem.id.asc())
        )
        return self.session.execute(stmt).scalars().all()


class SaleRevenueRepository(TenantRepository[Sale]):
    """Agrégats de revenu et de coût des ventes, pour la bande E (lecture seule).

    Les mesures sont celles du § 4.10, à la lettre : la phase 08 remplacera la
    source par `daily_sales_facts` sans changer un seul chiffre, et l'écart entre
    les deux deviendra le test T32.

    Deux requêtes plutôt qu'une jointure unique : agréger les lignes de vente et
    leurs retours ensemble **dupliquerait** chaque ligne vendue autant de fois
    qu'elle a été retournée. C'est exactement la surestimation que la V1.1 corrige
    en pré-agrégeant les retours (§ 6.1) ; le même piège attend ici.

    Les produits `qty × prix` et `qty × coût` sont arrondis **à la ligne**, comme
    `sale_items.net_amount` l'est déjà par sa définition générée en base. C'est ce qui
    rend cette source et `daily_sales_facts` égales par construction : sans cet
    arrondi, la table de faits arrondirait chaque total jour × produit dans ses
    colonnes `numeric(14,2)` et l'écart s'accumulerait sur 90 jours — T32 passerait
    ou échouerait selon le jeu de données (ADR 0034).
    """

    model = Sale

    #: Une vente annulée n'a produit ni revenu ni coût, un brouillon non plus.
    CONFIRMED = "confirmed"

    def gross_totals(self, *, period_from: datetime, period_to: datetime) -> dict[str, Decimal]:
        """CA brut, remises, taxes et coût des marchandises sorties."""
        stmt = (
            select(
                func.coalesce(func.sum(func.round(SaleItem.qty * SaleItem.unit_price, 2)), 0),
                func.coalesce(func.sum(SaleItem.discount), 0),
                func.coalesce(func.sum(SaleItem.tax_amount), 0),
                func.coalesce(func.sum(func.round(SaleItem.qty * SaleItem.unit_cost, 2)), 0),
            )
            .select_from(SaleItem)
            .join(
                Sale,
                (Sale.company_id == SaleItem.company_id) & (Sale.id == SaleItem.sale_id),
            )
            .where(
                Sale.company_id == self.ctx.company_id,
                Sale.status == self.CONFIRMED,
                Sale.sold_at >= period_from,
                Sale.sold_at <= period_to,
            )
        )
        gross, discount, tax, cogs = self.session.execute(stmt).one()
        return {
            "gross_revenue": Decimal(gross),
            "discount_total": Decimal(discount),
            "tax_total": Decimal(tax),
            "cogs_gross": Decimal(cogs),
        }

    def return_totals(self, *, period_from: datetime, period_to: datetime) -> dict[str, Decimal]:
        """Montant HT rendu et coût réintégré, **rattachés au jour de la vente**.

        Un retour enregistré aujourd'hui corrige une vente d'il y a trois semaines
        (§ 4.10) : la période porte donc sur `sales.sold_at`, jamais sur la date du
        retour. Sinon la marge d'un mois clos changerait après coup.
        """
        stmt = (
            select(
                func.coalesce(
                    func.sum(SaleReturnItem.refund_amount - SaleReturnItem.tax_refund), 0
                ),
                func.coalesce(
                    func.sum(func.round(SaleReturnItem.qty * SaleReturnItem.unit_cost, 2)), 0
                ),
            )
            .select_from(SaleReturnItem)
            .join(
                SaleItem,
                (SaleItem.company_id == SaleReturnItem.company_id)
                & (SaleItem.id == SaleReturnItem.sale_item_id),
            )
            .join(
                Sale,
                (Sale.company_id == SaleItem.company_id) & (Sale.id == SaleItem.sale_id),
            )
            .where(
                Sale.company_id == self.ctx.company_id,
                Sale.status == self.CONFIRMED,
                Sale.sold_at >= period_from,
                Sale.sold_at <= period_to,
            )
        )
        refund_net, cogs_returned = self.session.execute(stmt).one()
        return {
            "refund_net_amount": Decimal(refund_net),
            "cogs_returned": Decimal(cogs_returned),
        }

    def confirmed_sale_count(self, *, period_from: datetime, period_to: datetime) -> int:
        """Nombre de ventes confirmées sur la période."""
        stmt = (
            select(func.count())
            .select_from(Sale)
            .where(
                Sale.company_id == self.ctx.company_id,
                Sale.status == self.CONFIRMED,
                Sale.sold_at >= period_from,
                Sale.sold_at <= period_to,
            )
        )
        return int(self.session.execute(stmt).scalar_one())
