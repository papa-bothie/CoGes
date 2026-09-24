"""Requêtes du module Finance — filtrées par tenant, sans règle métier."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from app.core.repository import TenantRepository
from app.modules.finance.models import Debt, Payment, PaymentAllocation, SaleReturnRefund

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

    def for_return(self, sale_return_id: UUID) -> Sequence[Payment]:
        """Décaissements rattachés à un retour, du plus ancien au plus récent."""
        stmt = (
            self._select()
            .where(Payment.sale_return_id == sale_return_id)
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

    def get_open_for_sale_for_update(self, sale_id: UUID) -> Debt | None:
        """La dette encore ouverte de cette vente, verrouillée pour la transaction.

        `open` ou `partially_paid` seulement : une dette soldée ou abandonnée n'a plus
        rien à compenser, et la rendre ferait croire le contraire à l'appelant.
        """
        stmt = (
            self._select()
            .where(Debt.sale_id == sale_id, Debt.status.in_(OPEN_STATUSES))
            .with_for_update()
        )
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


class PaymentAllocationRepository(TenantRepository[PaymentAllocation]):
    """Lettrages paiement ↔ dette. Les soldes sont recalculés par `pa_rollup`."""

    model = PaymentAllocation

    def for_debt(self, debt_id: UUID) -> Sequence[PaymentAllocation]:
        """Affectations reçues par une dette, de la plus ancienne à la plus récente."""
        stmt = (
            self._select()
            .where(PaymentAllocation.debt_id == debt_id)
            .order_by(PaymentAllocation.created_at.asc(), PaymentAllocation.id.asc())
        )
        return self.session.execute(stmt).scalars().all()


class SaleReturnRefundRepository(TenantRepository[SaleReturnRefund]):
    """Lettrages retour ↔ paiement — les deux sens de la question du § 5.4."""

    model = SaleReturnRefund

    def for_return(self, sale_return_id: UUID) -> Sequence[SaleReturnRefund]:
        """« Quels remboursements pour ce retour » — index `srr_by_return`."""
        stmt = (
            self._select()
            .where(SaleReturnRefund.sale_return_id == sale_return_id)
            .order_by(SaleReturnRefund.created_at.asc(), SaleReturnRefund.id.asc())
        )
        return self.session.execute(stmt).scalars().all()

    def for_payment(self, payment_id: UUID) -> Sequence[SaleReturnRefund]:
        """« Quel retour a provoqué cette sortie » — index `srr_by_payment`."""
        stmt = (
            self._select()
            .where(SaleReturnRefund.payment_id == payment_id)
            .order_by(SaleReturnRefund.created_at.asc(), SaleReturnRefund.id.asc())
        )
        return self.session.execute(stmt).scalars().all()
