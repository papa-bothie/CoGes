"""Accès à `daily_sales_facts` : reconstruction et lectures agrégées.

La reconstruction est le § 6.1 du Modèle de données. Sa propriété essentielle tient
en une CTE : **les retours sont pré-agrégés par `sale_item_id` avant toute jointure**.
La V1 joignait directement `sale_items` à `sale_return_items` ; une ligne ayant reçu
trois retours partiels produisait alors trois lignes, donc trois fois la quantité
vendue, le CA, la remise, le COGS, et trois fois le même `sale_id` dans le comptage.
C'est le test **T29**.

Deux écarts assumés par rapport à la lettre du § 6.1, tous deux consignés en ADR :

* la CTE `cible` reçoit la liste des jours en paramètre (`unnest`) au lieu de la
  déduire de `business_events` — le jour vient du corps de l'événement, et un filet
  nocturne rattrape ce qu'un événement perdu aurait laissé de côté ;
* les produits `qty × prix` et `qty × coût` sont **arrondis à la ligne**, comme
  `sale_items.net_amount` l'est déjà en base. Sans cela, la somme d'un jour serait
  arrondie à l'insertion dans une colonne `numeric(14,2)` et l'écart s'accumulerait
  sur 90 jours : **T32** deviendrait vrai ou faux selon le jeu de données. Arrondir à
  la ligne rend les deux sources identiques par construction.

Et une **erreur du § 6.1 corrigée** : il agrège la catégorie par `max(category_id)`,
or PostgreSQL n'a pas d'agrégat `max()` sur `uuid` — la requête ne s'exécute pas
(« function max(uuid) does not exist », constaté). `category_id` vient d'une jointure
unique sur `products` par `product_id` : elle est donc constante dans chaque groupe et
entre simplement dans le `GROUP BY`. Le résultat est identique à l'intention du
document, sans conversion en texte ni choix arbitraire dans un tableau.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext

#: Corps commun aux deux requêtes de reconstruction. `cible` porte les jours à
#: réécrire ; `retours` garantit une ligne par ligne de vente ; `lignes` arrondit à
#: la ligne et n'inclut que les ventes `confirmed` — une vente annulée n'a produit ni
#: revenu ni coût, et un brouillon non plus.
_REBUILD_CTES = """
    WITH cible AS (
         SELECT unnest(CAST(:days AS date[])) AS day
    ),
    retours AS (
         SELECT ri.company_id, ri.sale_item_id,
                SUM(ri.qty)                                AS returned_qty,
                SUM(ri.refund_amount - ri.tax_refund)      AS refund_net_amount,
                SUM(round(ri.qty * ri.unit_cost, 2))       AS cogs_returned
           FROM sale_return_items ri
           JOIN sale_returns r
             ON r.company_id = ri.company_id AND r.id = ri.return_id
          WHERE ri.company_id = :company_id
          GROUP BY ri.company_id, ri.sale_item_id
    ),
    lignes AS (
         SELECT s.company_id,
                (s.sold_at AT TIME ZONE c.timezone)::date AS day,
                si.product_id, p.category_id, s.id AS sale_id,
                si.qty,
                round(si.qty * si.unit_price, 2)  AS gross_revenue,
                si.discount,
                si.tax_amount,
                round(si.qty * si.unit_cost, 2)   AS cogs_gross,
                COALESCE(rt.returned_qty, 0)      AS returned_qty,
                COALESCE(rt.refund_net_amount, 0) AS refund_net_amount,
                COALESCE(rt.cogs_returned, 0)     AS cogs_returned
           FROM sales s
           JOIN companies c   ON c.id = s.company_id
           JOIN sale_items si ON si.company_id = s.company_id AND si.sale_id = s.id
           JOIN products p    ON p.company_id = si.company_id AND p.id = si.product_id
           LEFT JOIN retours rt
             ON rt.company_id = si.company_id AND rt.sale_item_id = si.id   -- 1:0..1
          WHERE s.company_id = :company_id
            AND s.status = 'confirmed'
            AND (s.sold_at AT TIME ZONE c.timezone)::date IN (SELECT day FROM cible)
    )
"""

_UPSERT_FACTS = text(
    _REBUILD_CTES
    + """
    INSERT INTO daily_sales_facts AS f (
         company_id, day, product_id, category_id,
         qty_sold, returned_qty, net_qty_sold,
         gross_revenue, discount_total, tax_total, refund_net_amount, net_revenue,
         cogs_gross, cogs_returned, cogs_net, sale_count, built_at)
    SELECT company_id, day, product_id, category_id,
           SUM(qty)                                                  AS qty_sold,
           SUM(returned_qty)                                         AS returned_qty,
           SUM(qty) - SUM(returned_qty)                              AS net_qty_sold,
           SUM(gross_revenue)                                        AS gross_revenue,
           SUM(discount)                                             AS discount_total,
           SUM(tax_amount)                                           AS tax_total,
           SUM(refund_net_amount)                                    AS refund_net_amount,
           SUM(gross_revenue) - SUM(discount) - SUM(refund_net_amount) AS net_revenue,
           SUM(cogs_gross)                                           AS cogs_gross,
           SUM(cogs_returned)                                        AS cogs_returned,
           SUM(cogs_gross) - SUM(cogs_returned)                      AS cogs_net,
           COUNT(DISTINCT sale_id)                                   AS sale_count,
           now()
      FROM lignes
     GROUP BY company_id, day, product_id, category_id
    ON CONFLICT (company_id, day, product_id) DO UPDATE SET
         category_id = EXCLUDED.category_id, qty_sold = EXCLUDED.qty_sold,
         returned_qty = EXCLUDED.returned_qty, net_qty_sold = EXCLUDED.net_qty_sold,
         gross_revenue = EXCLUDED.gross_revenue, discount_total = EXCLUDED.discount_total,
         tax_total = EXCLUDED.tax_total, refund_net_amount = EXCLUDED.refund_net_amount,
         net_revenue = EXCLUDED.net_revenue, cogs_gross = EXCLUDED.cogs_gross,
         cogs_returned = EXCLUDED.cogs_returned, cogs_net = EXCLUDED.cogs_net,
         sale_count = EXCLUDED.sale_count, built_at = now()
    """
)

#: Les lignes devenues vides (vente annulée, dernière ligne supprimée) sont purgées
#: pour les jours reconstruits, sinon un fait fantôme subsiste. C'est le test **T31**.
_PURGE_FACTS = text(
    _REBUILD_CTES
    + """
    DELETE FROM daily_sales_facts d
     WHERE d.company_id = :company_id
       AND d.day IN (SELECT day FROM cible)
       AND NOT EXISTS (SELECT 1 FROM lignes l
                        WHERE l.company_id = d.company_id AND l.day = d.day
                          AND l.product_id = d.product_id)
    """
)

_PERIOD_TOTALS = text(
    """
    SELECT COALESCE(SUM(gross_revenue), 0)     AS gross_revenue,
           COALESCE(SUM(discount_total), 0)    AS discount_total,
           COALESCE(SUM(tax_total), 0)         AS tax_total,
           COALESCE(SUM(refund_net_amount), 0) AS refund_net_amount,
           COALESCE(SUM(net_revenue), 0)       AS net_revenue,
           COALESCE(SUM(cogs_gross), 0)        AS cogs_gross,
           COALESCE(SUM(cogs_returned), 0)     AS cogs_returned,
           COALESCE(SUM(cogs_net), 0)          AS cogs_net
      FROM daily_sales_facts
     WHERE company_id = :company_id
       AND day BETWEEN :period_from AND :period_to
    """
)

_DAILY_SERIES = text(
    """
    SELECT day,
           COALESCE(SUM(net_revenue), 0)              AS net_revenue,
           COALESCE(SUM(net_revenue - cogs_net), 0)   AS margin
      FROM daily_sales_facts
     WHERE company_id = :company_id
       AND day BETWEEN :period_from AND :period_to
     GROUP BY day
     ORDER BY day
    """
)

#: Agrégats par produit sur la période. Les sept métriques calculables ici dérivent
#: toutes de ces colonnes ; aucune n'est fusionnée avec une autre (décision 12).
#:
#: `sale_count` se somme légitimement entre jours : une vente appartient à un seul
#: jour, donc une même vente ne peut pas être comptée deux fois — ce qui n'est pas
#: vrai entre produits, et c'est pourquoi le nombre de tickets d'une période ne se
#: lit jamais ici.
_PRODUCT_TOTALS = text(
    """
    SELECT f.product_id,
           p.name                                   AS product_name,
           COALESCE(SUM(f.net_revenue), 0)          AS net_revenue,
           COALESCE(SUM(f.net_revenue - f.cogs_net), 0) AS margin,
           COALESCE(SUM(f.net_qty_sold), 0)         AS net_qty_sold,
           COALESCE(SUM(f.sale_count), 0)           AS sale_count
      FROM daily_sales_facts f
      JOIN products p ON p.company_id = f.company_id AND p.id = f.product_id
     WHERE f.company_id = :company_id
       AND f.day BETWEEN :period_from AND :period_to
     GROUP BY f.product_id, p.name
    """
)


class DailySalesFactRepository:
    """Requêtes de `daily_sales_facts`. Aucune règle métier ici."""

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    # ------------------------------------------------------------- reconstruction

    def rebuild_days(self, days: list[dt.date]) -> None:
        """Réécrit les jours donnés, puis purge ceux devenus vides.

        Les deux requêtes partagent le même corps de CTE, donc la même définition de
        « ce qui est vrai aujourd'hui » : un fait absent de l'une est purgé par l'autre.
        L'ordre importe — purger d'abord réinsérerait ensuite ce qu'on vient d'enlever.
        """
        if not days:
            return
        params = {"company_id": self.ctx.company_id, "days": sorted(set(days))}
        self.session.execute(_UPSERT_FACTS, params)
        self.session.execute(_PURGE_FACTS, params)

    # -------------------------------------------------------------------- lectures

    def period_totals(self, *, period_from: dt.date, period_to: dt.date) -> dict[str, Decimal]:
        """Les huit mesures du § 4.10 sommées sur la période."""
        row = self.session.execute(
            _PERIOD_TOTALS,
            {
                "company_id": self.ctx.company_id,
                "period_from": period_from,
                "period_to": period_to,
            },
        ).one()
        return {
            "gross_revenue": Decimal(row.gross_revenue),
            "discount_total": Decimal(row.discount_total),
            "tax_total": Decimal(row.tax_total),
            "refund_net_amount": Decimal(row.refund_net_amount),
            "net_revenue": Decimal(row.net_revenue),
            "cogs_gross": Decimal(row.cogs_gross),
            "cogs_returned": Decimal(row.cogs_returned),
            "cogs_net": Decimal(row.cogs_net),
        }

    def daily_series(
        self, *, period_from: dt.date, period_to: dt.date
    ) -> list[tuple[dt.date, Decimal, Decimal]]:
        """Revenu net et marge par jour. Les jours sans vente sont **absents** ici."""
        rows = self.session.execute(
            _DAILY_SERIES,
            {
                "company_id": self.ctx.company_id,
                "period_from": period_from,
                "period_to": period_to,
            },
        ).all()
        return [(row.day, Decimal(row.net_revenue), Decimal(row.margin)) for row in rows]

    def product_totals(self, *, period_from: dt.date, period_to: dt.date) -> list[dict[str, Any]]:
        """Agrégats par produit, sans classement : le tri appartient au service."""
        rows = self.session.execute(
            _PRODUCT_TOTALS,
            {
                "company_id": self.ctx.company_id,
                "period_from": period_from,
                "period_to": period_to,
            },
        ).all()
        return [
            {
                "product_id": row.product_id,
                "product_name": row.product_name,
                "net_revenue": Decimal(row.net_revenue),
                "margin": Decimal(row.margin),
                "net_qty_sold": Decimal(row.net_qty_sold),
                "sale_count": int(row.sale_count),
            }
            for row in rows
        ]

    def product_ids(self, *, period_from: dt.date, period_to: dt.date) -> list[UUID]:
        """Produits ayant bougé sur la période — l'univers des classements."""
        return [
            row["product_id"]
            for row in self.product_totals(period_from=period_from, period_to=period_to)
        ]
