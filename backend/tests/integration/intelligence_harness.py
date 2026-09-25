"""Outils communs aux tests de CoGes Intelligence (phase 09).

Chaque test fabrique **sa** boutique : le pipeline écrit des insights et des
prévisions pour toute l'entreprise, et un historique de ventes ne se prête pas plus
qu'un stock. L'entreprise passe par la vraie commande d'onboarding — un gérant réel,
avec ses rôles, reçoit donc les notifications d'insight critique.

Les ventes sont écrites en SQL brut sous `coges_app` puis antidatées (`sold_at` n'est
pas borné, ADR 0015) ; le stock, lui, est réceptionné **maintenant**, l'antidatage d'un
mouvement étant plafonné à 48 h. Le pipeline tourne sous `coges_analytics`, comme en
production.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.intelligence.estimators.artifacts import ArtifactStore
from app.modules.intelligence.pipelines import (
    FeatureRun,
    InferenceResult,
    run_features,
    run_inference,
)
from tests.conftest import DemoCompany, _create_demo_company
from tests.integration import facts_harness as facts
from tests.integration import sales_harness as sales


@dataclass(frozen=True)
class Shop:
    """Une boutique de test : l'entreprise, et de quoi écrire en son nom."""

    company: DemoCompany

    @property
    def company_id(self) -> UUID:
        return self.company.company_id

    @property
    def user_id(self) -> UUID:
        return self.company.manager_id

    @property
    def ctx(self) -> TenantContext:
        return TenantContext(user_id=self.company.manager_id, company_id=self.company_id)


def new_shop(prefix: str) -> Shop:
    return Shop(_create_demo_company(f"{prefix}-{uuid4().hex[:8]}"))


def today() -> dt.date:
    """Jour courant dans le fuseau des entreprises de test (Africa/Dakar = UTC)."""
    return dt.datetime.now(dt.UTC).date()


def noon(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(12, 0), tzinfo=dt.UTC)


def add_product(
    session: Session, shop: Shop, name: str, *, tracked: bool = True, price: str = "1000"
) -> UUID:
    product_id = uuid4()
    session.execute(
        text(
            "INSERT INTO products (id, company_id, sku, name, unit, is_stock_tracked) "
            "VALUES (:id, :company_id, :sku, :name, 'piece', :tracked)"
        ),
        {
            "id": product_id,
            "company_id": shop.company_id,
            "sku": f"SKU-{product_id.hex[:8]}",
            "name": name,
            "tracked": tracked,
        },
    )
    session.execute(
        text(
            "INSERT INTO product_prices (company_id, product_id, unit_price, cost_price, "
            "created_by) VALUES (:company_id, :product_id, :price, 600, :user_id)"
        ),
        {
            "company_id": shop.company_id,
            "product_id": product_id,
            "price": Decimal(price),
            "user_id": shop.user_id,
        },
    )
    return product_id


def stock_in(session: Session, shop: Shop, product_id: UUID, qty: str) -> None:
    """Réception de stock **maintenant**."""
    session.execute(
        text(
            "INSERT INTO inventory_movements "
            "(company_id, product_id, type, qty_delta, unit_cost, created_by) "
            "VALUES (:company_id, :product_id, 'purchase_in', :qty, 600, :user_id)"
        ),
        {
            "company_id": shop.company_id,
            "product_id": product_id,
            "qty": Decimal(qty),
            "user_id": shop.user_id,
        },
    )


def sell(
    session: Session,
    shop: Shop,
    product_id: UUID,
    *,
    day: dt.date,
    qty: str,
    unit_price: str = "1000",
    unit_cost: str = "600",
) -> tuple[UUID, UUID]:
    """Une vente confirmée d'une ligne, antidatée à midi du jour donné."""
    return facts.sold_line(
        session,
        shop,  # type: ignore[arg-type]
        product_id,
        qty=qty,
        unit_price=unit_price,
        unit_cost=unit_cost,
        tax_rate="0",
        sold_at=noon(day),
    )


def sell_daily(
    session: Session,
    shop: Shop,
    product_id: UUID,
    *,
    until: dt.date,
    days: int,
    pattern: tuple[int, ...] = (2, 3, 2, 3, 4, 6, 5),
) -> None:
    """Une vente par jour sur `days` jours jusqu'à `until`, quantité selon le jour de semaine."""
    for offset in range(days):
        day = until - dt.timedelta(days=offset)
        sell(session, shop, product_id, day=day, qty=str(pattern[day.weekday()]))


def cancel(session: Session, shop: Shop, sale_id: UUID) -> None:
    sales.cancel(session, shop, sale_id)  # type: ignore[arg-type]


def give_back(session: Session, shop: Shop, sale_id: UUID, item_id: UUID, qty: str) -> None:
    facts.returned(
        session,
        shop,  # type: ignore[arg-type]
        sale_id,
        item_id,
        qty=qty,
        tax_rate="0",
    )


def write(app_factory: sessionmaker[Any], shop: Shop) -> Any:
    """Transaction applicative (`coges_app`) au nom de la boutique."""
    return tenant_transaction(shop.ctx, session_factory=app_factory)


def features(
    analytics_factory: sessionmaker[Any], shop: Shop, *, as_of: dt.date
) -> FeatureRun | None:
    ctx = TenantContext.bootstrap(shop.company_id)
    with tenant_transaction(ctx, session_factory=analytics_factory) as session:
        return run_features(session, ctx, as_of=as_of)


def pipeline(
    analytics_factory: sessionmaker[Any],
    shop: Shop,
    *,
    as_of: dt.date,
    store: ArtifactStore,
) -> InferenceResult | None:
    """Étapes 04 à 07, comme les tâches nocturnes, sous `coges_analytics`."""
    ctx = TenantContext.bootstrap(shop.company_id)
    with tenant_transaction(ctx, session_factory=analytics_factory) as session:
        run_features(session, ctx, as_of=as_of)
        return run_inference(session, ctx, as_of=as_of, store=store)


def rows(factory: sessionmaker[Any], shop: Shop, sql: str, **params: Any) -> list[Any]:
    """Lit à travers la RLS, dans le contexte de la boutique."""
    ctx = TenantContext.bootstrap(shop.company_id)
    with tenant_transaction(ctx, session_factory=factory) as session:
        return list(session.execute(text(sql), params).all())


def set_intelligence(app_factory: sessionmaker[Any], shop: Shop, *, enabled: bool) -> None:
    with write(app_factory, shop) as session:
        session.execute(
            text(
                "UPDATE companies SET settings = settings || "
                "jsonb_build_object('intelligence_enabled', CAST(:enabled AS boolean)) "
                "WHERE id = :id"
            ),
            {"enabled": enabled, "id": shop.company_id},
        )
