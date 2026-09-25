"""Outils communs aux tests qui dépendent de `daily_sales_facts`.

Pour T29 à T32, tout passe par du SQL brut en `coges_app` : le sujet du test est la
**requête de reconstruction**, pas le service qui l'appelle. On construit donc des
ventes et des retours à la main, on lance `rebuild_days`, et on relit les faits
produits.

Depuis la phase 08, `/analytics/overview` et `/dashboard` lisent eux aussi ces faits.
Les tests d'API n'ont pas de worker pour les construire : `rebuild` et `rebuild_around`
font ce travail à leur place, sous le rôle qui le fait en production.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.analytics import service as analytics_service
from app.modules.analytics.repository import DailySalesFactRepository
from tests.integration import sales_harness as sales
from tests.tenancy.harness import Tenant

_INSERT_PRODUCT = text(
    """
    INSERT INTO products (id, company_id, category_id, sku, name, unit)
    VALUES (:id, :company_id, :category_id, :sku, :name, 'piece')
    """
)

_BACKDATE_SALE = text(
    "UPDATE sales SET sold_at = :sold_at WHERE company_id = :company_id AND id = :id"
)

_READ_FACT = text(
    """
    SELECT qty_sold, returned_qty, net_qty_sold, gross_revenue, discount_total,
           tax_total, refund_net_amount, net_revenue, cogs_gross, cogs_returned,
           cogs_net, sale_count, category_id
      FROM daily_sales_facts
     WHERE company_id = :company_id AND day = :day AND product_id = :product_id
    """
)

_READ_DAY = text(
    """
    SELECT product_id, qty_sold, returned_qty, net_qty_sold, gross_revenue,
           discount_total, tax_total, refund_net_amount, net_revenue, cogs_gross,
           cogs_returned, cogs_net, sale_count
      FROM daily_sales_facts
     WHERE company_id = :company_id AND day = :day
     ORDER BY product_id
    """
)


def extra_product(session: Session, tenant: Tenant, sku: str) -> UUID:
    """Un second produit, pour comparer deux lignes de fait côte à côte."""
    product_id = uuid4()
    session.execute(
        _INSERT_PRODUCT,
        {
            "id": product_id,
            "company_id": tenant.company_id,
            "category_id": tenant.category_id,
            "sku": sku,
            "name": f"Produit {sku}",
        },
    )
    return product_id


def backdate(session: Session, tenant: Tenant, sale_id: UUID, sold_at: dt.datetime) -> None:
    """Antidate une vente.

    `sales.sold_at` n'est pas borné — contrairement à `inventory_movements.occurred_at`
    (ADR 0015) — parce que le mouvement de stock, lui, est daté de la confirmation.
    C'est ce qui permet de fabriquer quatre-vingt-dix jours d'historique en un test.
    """
    session.execute(
        _BACKDATE_SALE,
        {"sold_at": sold_at, "company_id": tenant.company_id, "id": sale_id},
    )


def sold_line(
    session: Session,
    tenant: Tenant,
    product_id: UUID,
    *,
    qty: str,
    unit_price: str = "1000",
    unit_cost: str = "600",
    discount: str = "0",
    tax_rate: str = "0.18",
    sold_at: dt.datetime | None = None,
) -> tuple[UUID, UUID]:
    """Une vente confirmée d'une seule ligne. Renvoie `(sale_id, sale_item_id)`."""
    sale_id = sales.make_sale(session, tenant)
    item_id = sales.add_line(
        session,
        tenant,
        sale_id,
        product_id,
        qty=qty,
        unit_price=unit_price,
        unit_cost=unit_cost,
        discount=discount,
        tax_rate=tax_rate,
    )
    sales.confirm(session, tenant, sale_id)
    if sold_at is not None:
        backdate(session, tenant, sale_id, sold_at)
    return sale_id, item_id


def returned(
    session: Session,
    tenant: Tenant,
    sale_id: UUID,
    sale_item_id: UUID,
    *,
    qty: str,
    unit_price: str = "1000",
    tax_rate: str = "0.18",
    unit_cost: str = "600",
) -> UUID:
    """Un retour partiel d'une ligne de vente, montants calculés au prorata.

    Le remboursable est arrondi net et taxe **séparément** (ADR 0026) : on reproduit
    la même arithmétique ici, sinon le test comparerait deux définitions du retour.
    """
    net = (Decimal(qty) * Decimal(unit_price)).quantize(Decimal("0.01"))
    tax = (net * Decimal(tax_rate)).quantize(Decimal("0.01"))
    return_id = sales.make_return(session, tenant, sale_id)
    sales.return_line(
        session,
        tenant,
        return_id,
        sale_item_id,
        qty=qty,
        refund_amount=str(net + tax),
        tax_refund=str(tax),
        unit_cost=unit_cost,
    )
    return return_id


def read_fact(session: Session, tenant: Tenant, day: dt.date, product_id: UUID) -> Any:
    """La ligne de fait d'un jour et d'un produit, ou `None` si elle a été purgée."""
    return session.execute(
        _READ_FACT,
        {"company_id": tenant.company_id, "day": day, "product_id": product_id},
    ).one_or_none()


def read_day(session: Session, tenant: Tenant, day: dt.date) -> Any:
    """Toutes les lignes de fait d'un jour, triées, pour comparer deux passages."""
    return session.execute(_READ_DAY, {"company_id": tenant.company_id, "day": day}).all()


# ------------------------------------------------------ reconstruction des faits


def rebuild(
    analytics_factory: sessionmaker[Any], company_id: UUID, days: Sequence[dt.date]
) -> None:
    """Reconstruit `daily_sales_facts` pour ces jours, **en `coges_analytics`**.

    Ce que le worker analytique fait après COMMIT, fait ici à la main : aucune tâche
    Celery ne tourne pendant la suite, et depuis la phase 08 l'overview lit les faits
    plutôt que `sale_items`. Un test qui confirme une vente puis interroge
    `/analytics/overview` sans passer par ici mesure une projection vide.

    Le rôle importe. La purge des faits devenus vides est un `DELETE`, que `coges_app`
    n'a le droit de faire nulle part (T36) : lancer la reconstruction sous le rôle
    applicatif ferait échouer T31 pour une raison qui n'existe pas en production.
    """
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx, session_factory=analytics_factory) as session:
        DailySalesFactRepository(session, ctx).rebuild_days(list(days))


def rebuild_around(
    analytics_factory: sessionmaker[Any],
    session_factory: sessionmaker[Any],
    company_id: UUID,
    *,
    back: int = 0,
) -> dt.date:
    """Reconstruit le jour courant de l'entreprise, et les `back` jours qui précèdent.

    Le jour est celui du **fuseau de l'entreprise** (§ 4.10), pas celui d'UTC : à
    Dakar comme à Londres ils coïncident, mais la borne de `/analytics/overview` est
    calculée dans le fuseau, et deux définitions du « jour » feraient diverger le test
    du code qu'il éprouve. Renvoie ce jour, pour que l'appelant puisse le réutiliser.
    """
    today = today_in_company(session_factory, company_id)
    rebuild(
        analytics_factory,
        company_id,
        [today - dt.timedelta(days=offset) for offset in range(back + 1)],
    )
    return today


def today_in_company(session_factory: sessionmaker[Any], company_id: UUID) -> dt.date:
    """Date du jour dans le fuseau de l'entreprise."""
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        return analytics_service.today_in_company(session, ctx)
