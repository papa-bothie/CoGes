"""Étapes 02-03 du Diagramme 7 : collecte au point D et préparation.

Tout passe par les façades des modules amont : Intelligence ne lit aucune table
transactionnelle directement. Ce qui sort d'ici est une série **dense** — les jours
sans vente valent zéro, sans quoi toute moyenne mobile est biaisée à la hausse (§ 6.2)
— et chaque jour porte son signal de rupture, reconstitué **à la date**.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.inventory import service as inventory_service
from app.modules.products.schemas import ProductSummary
from app.modules.sales import service as sales_service

ZERO = Decimal(0)


@dataclass(frozen=True)
class ProductHistory:
    """Série jour par jour d'un produit, de `days[0]` à `as_of` inclus."""

    product_id: UUID
    name: str
    stock_tracked: bool
    days: list[date]
    qty: list[Decimal]
    revenue: list[Decimal]
    cogs: list[Decimal]
    #: Stock du soir, `None` pour un produit non suivi en stock ou encore inconnu du
    #: journal au soir de D.
    on_hand: list[Decimal] | None
    #: Jour de rupture : demande **censurée**, pas demande nulle.
    censored: list[bool]
    first_sale_day: date | None

    def floats(self) -> list[float]:
        """Quantités en flottants, pour les estimateurs — jamais pour un montant."""
        return [float(value) for value in self.qty]


def load_histories(
    session: Session,
    ctx: TenantContext,
    *,
    products: dict[UUID, ProductSummary],
    as_of: date,
    window_days: int,
    timezone: str,
) -> dict[UUID, ProductHistory]:
    """Séries denses de tous les produits, telles qu'elles étaient connues au soir de D.

    Un jour est une rupture quand le produit est suivi en stock, que le journal le
    connaît déjà, et que son stock du soir est nul. Avant le premier mouvement, un
    stock nul n'est pas une rupture mais une absence de suivi.
    """
    day_from = as_of - timedelta(days=window_days - 1)
    days = [day_from + timedelta(days=offset) for offset in range(window_days)]
    index = {day: position for position, day in enumerate(days)}

    qty = {pid: [ZERO] * window_days for pid in products}
    revenue = {pid: [ZERO] * window_days for pid in products}
    cogs = {pid: [ZERO] * window_days for pid in products}
    for row in sales_service.daily_product_sales_as_of(
        session, ctx, day_from=day_from, as_of=as_of, timezone=timezone
    ):
        if row.product_id not in products:
            continue
        position = index[row.day]
        qty[row.product_id][position] = row.qty
        revenue[row.product_id][position] = row.revenue
        cogs[row.product_id][position] = row.cogs

    first_sales = sales_service.first_sale_days_as_of(session, ctx, as_of=as_of, timezone=timezone)

    tracked = [pid for pid, summary in products.items() if summary.is_stock_tracked]
    on_hand: dict[UUID, list[Decimal]] = {pid: [ZERO] * window_days for pid in tracked}
    known_since: dict[UUID, date | None] = {}
    for product_id, day, evening, first_day in inventory_service.daily_on_hand(
        session,
        ctx,
        product_ids=tracked,
        period_from=day_from,
        period_to=as_of,
        timezone=timezone,
    ):
        on_hand[product_id][index[day]] = evening
        known_since[product_id] = first_day

    histories: dict[UUID, ProductHistory] = {}
    for product_id, summary in products.items():
        since = known_since.get(product_id)
        # Un produit que le journal ne connaît pas encore au soir de D n'a pas un stock
        # nul : il a un stock **inconnu**. Le traiter comme zéro annoncerait une
        # rupture en cours sur tout article réceptionné après D.
        evenings = on_hand.get(product_id) if since is not None and since <= as_of else None
        censored = [
            evenings is not None and since is not None and day >= since and evenings[position] <= 0
            for position, day in enumerate(days)
        ]
        histories[product_id] = ProductHistory(
            product_id=product_id,
            name=summary.name,
            stock_tracked=summary.is_stock_tracked,
            days=days,
            qty=qty[product_id],
            revenue=revenue[product_id],
            cogs=cogs[product_id],
            on_hand=evenings,
            censored=censored,
            first_sale_day=first_sales.get(product_id),
        )
    return histories
