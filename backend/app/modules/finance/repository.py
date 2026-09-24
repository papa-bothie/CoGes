"""Requêtes du module Finance — filtrées par tenant, sans règle métier."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from app.core.repository import TenantRepository
from app.modules.finance.models import Debt, Payment

#: Statuts d'une dette encore vivante, au sens du plafond de crédit (§ 8.7).
OPEN_STATUSES = ("open", "partially_paid")


class PaymentRepository(TenantRepository[Payment]):
    model = Payment

    def for_sale(self, sale_id: UUID) -> Sequence[Payment]:
        """Tous les règlements d'une vente, du plus ancien au plus récent."""
        stmt = (
            self._select()
            .where(Payment.sale_id == sale_id)
            .order_by(Payment.paid_at.asc(), Payment.id.asc())
        )
        return self.session.execute(stmt).scalars().all()

    def inflow_count_for_sale(self, sale_id: UUID) -> int:
        """Nombre d'encaissements rattachés à la vente."""
        stmt = (
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.company_id == self.ctx.company_id,
                Payment.sale_id == sale_id,
                Payment.direction == "inflow",
            )
        )
        return int(self.session.execute(stmt).scalar_one())


class DebtRepository(TenantRepository[Debt]):
    model = Debt

    def for_sale(self, sale_id: UUID) -> Debt | None:
        """La dette née de cette vente, s'il y en a une.

        Une vente engendre au plus une dette : son solde impayé à la confirmation.
        """
        stmt = self._select().where(Debt.sale_id == sale_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def open_balance_for_customer(self, customer_id: UUID) -> Decimal:
        """Encours du client : somme des soldes de ses dettes encore ouvertes.

        Même définition que le trigger `debt_credit_limit`, pour que le refus
        applicatif et le refus de la base parlent du même chiffre.
        """
        stmt = select(func.coalesce(func.sum(Debt.balance), 0)).where(
            Debt.company_id == self.ctx.company_id,
            Debt.customer_id == customer_id,
            Debt.status.in_(OPEN_STATUSES),
        )
        return Decimal(self.session.execute(stmt).scalar_one())
