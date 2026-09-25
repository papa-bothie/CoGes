"""Table de projection du module Analytics : `daily_sales_facts` (§ 4.10).

Grain **entreprise × jour de vente × produit**. Table réelle et non vue
matérialisée : une vue matérialisée n'est pas soumise aux politiques RLS de ses
sources, et l'exposer à l'API rouvrirait un chemin de lecture sans barrière tenant.

Aucune décision métier ne s'appuie sur cette table : elle est intégralement
reconstruisible depuis le transactionnel, et c'est ce qui autorise le seul `DELETE`
du projet (rôle `coges_analytics`, ADR 0032).

Le jour est celui de `sales.sold_at` converti dans le fuseau de l'entreprise, et les
retours sont rattachés au jour de la **vente d'origine**, jamais au leur : un retour
enregistré aujourd'hui réécrit une ligne datée d'il y a trois semaines.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import NOW, TenantBase


class DailySalesFact(TenantBase):
    """Une journée de vente d'un produit, telle qu'elle s'est terminée."""

    __tablename__ = "daily_sales_facts"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, nullable=False
    )
    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    qty_sold: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    returned_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    net_qty_sold: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)

    gross_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    refund_net_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    net_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    cogs_gross: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    cogs_returned: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    cogs_net: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    sale_count: Mapped[int] = mapped_column(Integer, nullable=False)

    built_at: Mapped[dt.datetime] = mapped_column(server_default=NOW, nullable=False)
