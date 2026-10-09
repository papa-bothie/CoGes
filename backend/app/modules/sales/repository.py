"""Requêtes du module Sales — filtrées par tenant, sans règle métier."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, exists, false, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.repository import MAX_PAGE_SIZE, TenantRepository
from app.core.tenancy import TenantContext
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
        state: str | None = None,
        search_customer_ids: Sequence[UUID] | None = None,
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
        # Recherche : un numéro **exact** (jamais de `LIKE`, ADR 0013) ou l'un des clients
        # trouvés par leur nom. Sans ni l'un ni l'autre, la recherche ne trouve rien.
        found: list[ColumnElement[bool]] = []
        if sale_no is not None:
            found.append(Sale.sale_no == sale_no)
        if search_customer_ids:
            found.append(Sale.customer_id.in_(list(search_customer_ids)))
        if sale_no is not None or search_customer_ids is not None:
            filters.append(or_(*found) if found else false())
        if state is not None:
            filters.append(self._state(state))
        return filters

    def _state(self, state: str) -> ColumnElement[bool]:
        """Les quatre puces d'état de la liste (ADR 0070), toutes dérivées."""
        if state == "cancelled":
            return Sale.status == "cancelled"
        if state == "returned":
            return exists().where(
                SaleReturn.company_id == Sale.company_id, SaleReturn.sale_id == Sale.id
            )
        confirmed = Sale.status == "confirmed"
        if state == "paid":
            return confirmed & (Sale.paid_total >= Sale.total)
        if state == "unpaid":
            return confirmed & (Sale.paid_total < Sale.total)
        raise ValueError(f"État de vente inconnu : {state!r}")

    def recent_customer_ids(self, *, limit: int) -> list[UUID]:
        """Clients des dernières ventes confirmées, du plus récent au plus ancien."""
        last_sale = func.max(Sale.sold_at)
        stmt = (
            select(Sale.customer_id)
            .where(
                Sale.company_id == self.ctx.company_id,
                Sale.status == "confirmed",
                Sale.customer_id.is_not(None),
            )
            .group_by(Sale.customer_id)
            .order_by(last_sale.desc(), Sale.customer_id)
            .limit(limit)
        )
        return [row for row in self.session.execute(stmt).scalars().all() if row is not None]

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
        state: str | None = None,
        search_customer_ids: Sequence[UUID] | None = None,
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
                    state=state,
                    search_customer_ids=search_customer_ids,
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
        state: str | None = None,
        search_customer_ids: Sequence[UUID] | None = None,
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
                    state=state,
                    search_customer_ids=search_customer_ids,
                ),
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def day_totals(
        self, *, date_from: datetime, date_to: datetime, timezone: str
    ) -> list[tuple[date, int, Decimal]]:
        """Ventes confirmées par jour local, du plus récent au plus ancien."""
        day = func.date(func.timezone(timezone, Sale.sold_at))
        stmt = (
            select(day, func.count(), func.coalesce(func.sum(Sale.total), 0))
            .where(
                Sale.company_id == self.ctx.company_id,
                Sale.status == "confirmed",
                Sale.sold_at >= date_from,
                Sale.sold_at <= date_to,
            )
            .group_by(day)
            .order_by(day.desc())
        )
        return [(row[0], int(row[1]), Decimal(row[2])) for row in self.session.execute(stmt)]

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

    def counts_by_sale(self, sale_ids: Sequence[UUID]) -> dict[UUID, int]:
        """Nombre de lignes de chaque vente : une requête pour toute une page."""
        if not sale_ids:
            return {}
        stmt = (
            select(SaleItem.sale_id, func.count())
            .where(SaleItem.company_id == self.ctx.company_id, SaleItem.sale_id.in_(sale_ids))
            .group_by(SaleItem.sale_id)
        )
        return {sale_id: int(count) for sale_id, count in self.session.execute(stmt).all()}

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

    def returned_qty_by_item(self, sale_item_ids: Sequence[UUID]) -> dict[UUID, Decimal]:
        """Quantité déjà retournée, par ligne de vente (celles sans retour sont absentes)."""
        if not sale_item_ids:
            return {}
        stmt = (
            select(SaleReturnItem.sale_item_id, func.sum(SaleReturnItem.qty))
            .where(
                SaleReturnItem.company_id == self.ctx.company_id,
                SaleReturnItem.sale_item_id.in_(sale_item_ids),
            )
            .group_by(SaleReturnItem.sale_item_id)
        )
        return {item_id: Decimal(qty) for item_id, qty in self.session.execute(stmt).all()}


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


#: Borne de connaissance d'une date D : minuit du lendemain, dans le fuseau de
#: l'entreprise. Tout ce qui est horodaté **avant** a pu être connu à D.
_CUTOFF_CTE = """
    borne AS (
         SELECT (CAST(:as_of AS date) + 1)::timestamp AT TIME ZONE :timezone AS t
    ),
    valides AS (
         -- Point-in-time strict (ADR 0035) : une vente annulée **après** D était
         -- confirmée à D. Les brouillons n'ont jamais rien vendu.
         SELECT s.id, s.sold_at
           FROM sales s, borne
          WHERE s.company_id = :company_id
            AND s.sold_at < borne.t
            AND (s.status = 'confirmed'
                 OR (s.status = 'cancelled' AND s.cancelled_at >= borne.t))
    )
"""

#: Ventes jour × produit **telles qu'on les connaissait au soir de D** (§ 6.2).
#:
#: C'est la raison d'être de cette requête, et ce qui la distingue du § 6.1 :
#: `daily_sales_facts` est réécrite quand un retour arrive plus tard, et la relire
#: pour une date passée utiliserait un chiffre qui n'était pas connu ce jour-là.
#: Les retours sont donc pré-agrégés par ligne (pas de duplication, § 6.1) **et**
#: bornés à `returned_at < borne`. Produits arrondis à la ligne (ADR 0034).
_SALES_AS_OF = text(
    "WITH"
    + _CUTOFF_CTE
    + """
    , lignes AS (
         SELECT si.id, si.product_id, v.id AS sale_id,
                (v.sold_at AT TIME ZONE :timezone)::date AS day,
                si.qty,
                round(si.qty * si.unit_price, 2) - si.discount AS revenue,
                round(si.qty * si.unit_cost, 2)                AS cogs
           FROM valides v
           JOIN sale_items si ON si.company_id = :company_id AND si.sale_id = v.id
          WHERE (v.sold_at AT TIME ZONE :timezone)::date
                BETWEEN CAST(:day_from AS date) AND CAST(:as_of AS date)
    ),
    retours AS (
         SELECT ri.sale_item_id,
                SUM(ri.qty)                          AS qty,
                SUM(ri.refund_amount - ri.tax_refund) AS revenue,
                SUM(round(ri.qty * ri.unit_cost, 2))  AS cogs
           FROM sale_return_items ri
           JOIN sale_returns r ON r.company_id = ri.company_id AND r.id = ri.return_id
           CROSS JOIN borne
          WHERE ri.company_id = :company_id
            AND r.returned_at < borne.t
            AND ri.sale_item_id IN (SELECT id FROM lignes)
          GROUP BY ri.sale_item_id
    )
    SELECT l.day, l.product_id,
           SUM(l.qty - COALESCE(rt.qty, 0))         AS qty,
           SUM(l.revenue - COALESCE(rt.revenue, 0)) AS revenue,
           SUM(l.cogs - COALESCE(rt.cogs, 0))       AS cogs,
           COUNT(DISTINCT l.sale_id)                AS sale_count
      FROM lignes l
      LEFT JOIN retours rt ON rt.sale_item_id = l.id
     GROUP BY l.day, l.product_id
     ORDER BY l.product_id, l.day
    """
)

#: Premier jour de vente connu à D, par produit : le seuil d'historique en dépend.
_FIRST_SALE_AS_OF = text(
    "WITH"
    + _CUTOFF_CTE
    + """
    SELECT si.product_id, MIN((v.sold_at AT TIME ZONE :timezone)::date) AS first_day
      FROM valides v
      JOIN sale_items si ON si.company_id = :company_id AND si.sale_id = v.id
     GROUP BY si.product_id
    """
)


class SaleHistoryRepository:
    """Historique des ventes à une date de connaissance, pour CoGes Intelligence."""

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def daily_product_sales(
        self, *, day_from: date, as_of: date, timezone: str
    ) -> list[tuple[date, UUID, Decimal, Decimal, Decimal, int]]:
        rows = self.session.execute(
            _SALES_AS_OF,
            {
                "company_id": self.ctx.company_id,
                "day_from": day_from,
                "as_of": as_of,
                "timezone": timezone,
            },
        ).all()
        return [
            (
                row.day,
                row.product_id,
                Decimal(row.qty),
                Decimal(row.revenue),
                Decimal(row.cogs),
                int(row.sale_count),
            )
            for row in rows
        ]

    def first_sale_days(self, *, as_of: date, timezone: str) -> dict[UUID, date]:
        rows = self.session.execute(
            _FIRST_SALE_AS_OF,
            {"company_id": self.ctx.company_id, "as_of": as_of, "timezone": timezone},
        ).all()
        return {row.product_id: row.first_day for row in rows}
