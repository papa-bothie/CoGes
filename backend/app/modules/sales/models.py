"""Modèles du module Sales. Privés : aucun autre module ne les importe.

Les colonnes générées (`total`, `net_amount`, `tax_amount`, `line_total`) sont
déclarées en `Computed(..., persisted=True)` : SQLAlchemy sait alors qu'il ne doit
jamais les écrire, et qu'il faut les relire après un `flush`. L'égalité comptable
est **produite** par la base, pas vérifiée par le code (§ 4.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Computed, DateTime, Numeric, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import NOW, IdentifiedTenantBase

# Type créé par la révision 0001 : l'ORM le référence sans jamais le redéclarer.
SALE_STATUS = PG_ENUM("draft", "confirmed", "cancelled", name="sale_status", create_type=False)


class Sale(IdentifiedTenantBase):
    """En-tête d'une vente. Ses totaux sont maintenus par trigger, jamais en Python."""

    __tablename__ = "sales"

    customer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    sale_no: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(SALE_STATUS)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    #: Maintenus par `sale_recompute_totals` à chaque écriture sur `sale_items`.
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), Computed("subtotal - discount_total + tax_total", persisted=True)
    )
    #: Maintenu par `sale_paid_rollup` depuis `payments`, jamais écrit ici.
    paid_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


class SaleItem(IdentifiedTenantBase):
    """Ligne de vente. Figée dès que la vente quitte l'état `draft` (§ 4.5)."""

    __tablename__ = "sale_items"

    sale_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    product_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    #: Intervalle de `product_prices` d'où vient `unit_price` : la vente reste
    #: rattachable au tarif qui s'appliquait, même après plusieurs changements.
    price_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    #: CMP figé à la sortie de stock : le COGS historique de la ligne (§ 5.1 étape 5).
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    discount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), Computed("round(qty * unit_price - discount, 2)", persisted=True)
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        Computed("round((qty * unit_price - discount) * tax_rate, 2)", persisted=True),
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        Computed(
            "round(qty * unit_price - discount, 2)"
            " + round((qty * unit_price - discount) * tax_rate, 2)",
            persisted=True,
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


# Type créé par la révision 0001 : dérivé par `return_refund_status_set`, jamais écrit.
RETURN_REFUND_STATUS = PG_ENUM(
    "none_due", "pending", "partial", "settled", name="return_refund_status", create_type=False
)


class SaleReturn(IdentifiedTenantBase):
    """En-tête d'un retour client — un fait métier autonome, pas une annulation (§ 4.6).

    Aucune colonne de statut de retour : un retour existe ou n'existe pas. Le seul
    statut est celui de son **règlement**, et il est dérivé par trigger du couple
    (`total_refund`, `refunded_total`). Le code ne l'écrit jamais.
    """

    __tablename__ = "sale_returns"

    sale_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    return_no: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    returned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    # Ces trois colonnes portent leur défaut serveur pour que l'ORM les **omette**
    # de l'INSERT : sans cela, il y enverrait NULL. Le code ne les écrit jamais, et
    # c'est le seul moyen de le rendre vrai plutôt que de le promettre en commentaire.
    #: Maintenu par `return_recompute` depuis `sale_return_items`.
    total_refund: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    #: Maintenu par `refund_rollup` depuis `sale_return_refunds`.
    refunded_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    #: Dérivé par `return_refund_status_set`.
    refund_status: Mapped[str] = mapped_column(
        RETURN_REFUND_STATUS, server_default=text("'pending'")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


class SaleReturnItem(IdentifiedTenantBase):
    """Ligne de retour, calculée sur les snapshots de la ligne de vente (§ 4.7).

    `unit_cost` est recopié de `sale_items.unit_cost` : la marchandise revient au coût
    auquel elle est sortie, pas au CMP du jour (§ 5.3). `refund_amount` est TTC.
    """

    __tablename__ = "sale_return_items"

    return_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    sale_item_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_refund: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
