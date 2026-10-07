"""Requêtes du module Finance — filtrées par tenant, sans règle métier."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, Row, exists, func, select
from sqlalchemy.orm import aliased

from app.core.repository import TenantRepository
from app.modules.finance.models import Debt, Payment, PaymentAllocation, SaleReturnRefund
from app.modules.finance.schemas import OFFSET_METHOD

#: Statuts d'une dette encore vivante, au sens du plafond de crédit (§ 8.7).
OPEN_STATUSES = ("open", "partially_paid")

_Reversal = aliased(Payment, name="reversal")


def _is_cancelled() -> ColumnElement[bool]:
    """Le paiement courant a une contre-écriture (révision 0012)."""
    return exists().where(
        _Reversal.company_id == Payment.company_id,
        _Reversal.reversal_of_payment_id == Payment.id,
    )


def _counts_as_cash() -> list[ColumnElement[bool]]:
    """Ce qui est un vrai mouvement de caisse — la règle écrite une seule fois.

    Trois exclusions : les compensations (`offset`, ADR 0024), les paiements
    annulés et leurs annulations (ADR 0038). Une saisie erronée puis annulée n'a
    jamais eu lieu : elle sort des totaux des deux côtés, y compris sur son jour
    d'origine, et la trésorerie revient exactement à ce qu'elle était.
    """
    return [
        Payment.method != OFFSET_METHOD,
        Payment.reversal_of_payment_id.is_(None),
        ~_is_cancelled(),
    ]


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
        """Nombre d'encaissements **non annulés** rattachés à la vente."""
        stmt = (
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.company_id == self.ctx.company_id,
                Payment.sale_id == sale_id,
                Payment.direction == "inflow",
                ~_is_cancelled(),
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def reversal_of(self, payment_id: UUID) -> Payment | None:
        """La contre-écriture de ce paiement, s'il a été annulé."""
        stmt = self._select().where(Payment.reversal_of_payment_id == payment_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def lock_for_update(self, payment_ids: Sequence[UUID]) -> Sequence[Payment]:
        """Paiements du tenant, verrouillés dans l'ordre des ids.

        L'ordre fixe évite que deux annulations d'une même paire `offset` ne
        s'interbloquent. Le trigger `payment_reversal_check` prend le même verrou :
        l'avancer ici ne change pas l'autorité.
        """
        stmt = (
            self._select().where(Payment.id.in_(payment_ids)).order_by(Payment.id).with_for_update()
        )
        return self.session.execute(stmt).scalars().all()

    def reversals_for(self, payment_ids: Sequence[UUID]) -> Sequence[Payment]:
        """Contre-écritures d'un lot de paiements — une requête, pas N."""
        if not payment_ids:
            return []
        stmt = self._select().where(Payment.reversal_of_payment_id.in_(payment_ids))
        return self.session.execute(stmt).scalars().all()

    def offset_partners(self, payment: Payment) -> Sequence[Payment]:
        """L'autre moitié d'une compensation (ADR 0024).

        Les deux paiements d'une compensation naissent dans la même transaction :
        même `created_at` (l'horodatage de transaction de PostgreSQL), même auteur,
        même montant, sens opposé. Le service exige qu'il y en ait exactement un.
        """
        stmt = self._select().where(
            Payment.id != payment.id,
            Payment.method == OFFSET_METHOD,
            Payment.direction != payment.direction,
            Payment.amount == payment.amount,
            Payment.created_at == payment.created_at,
            Payment.created_by == payment.created_by,
            Payment.reversal_of_payment_id.is_(None),
        )
        return self.session.execute(stmt).scalars().all()

    def _period(
        self, *, period_from: datetime | None, period_to: datetime | None
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if period_from is not None:
            conditions.append(Payment.paid_at >= period_from)
        if period_to is not None:
            conditions.append(Payment.paid_at <= period_to)
        return conditions

    def count_filtered(
        self,
        *,
        direction: str | None = None,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Payment)
            .where(Payment.company_id == self.ctx.company_id)
            .where(*self._period(period_from=period_from, period_to=period_to))
        )
        if direction is not None:
            stmt = stmt.where(Payment.direction == direction)
        return int(self.session.execute(stmt).scalar_one())

    def page_filtered(
        self,
        *,
        page: int,
        page_size: int,
        direction: str | None = None,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> Sequence[Payment]:
        stmt = (
            self._select()
            .where(*self._period(period_from=period_from, period_to=period_to))
            .order_by(Payment.paid_at.desc(), Payment.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        if direction is not None:
            stmt = stmt.where(Payment.direction == direction)
        return self.session.execute(stmt).scalars().all()

    def cash_totals(self, *, period_from: datetime, period_to: datetime) -> dict[str, Decimal]:
        """Encaissé et décaissé de la période, hors compensations et annulations.

        La règle est `_counts_as_cash()` : écrite une fois, pour cette somme et pour
        la série quotidienne.
        """
        stmt = (
            select(Payment.direction, func.coalesce(func.sum(Payment.amount), 0))
            .where(
                Payment.company_id == self.ctx.company_id,
                *_counts_as_cash(),
                Payment.paid_at >= period_from,
                Payment.paid_at <= period_to,
            )
            .group_by(Payment.direction)
        )
        totals = {"inflow": Decimal("0"), "outflow": Decimal("0")}
        for direction, total in self.session.execute(stmt):
            totals[direction] = Decimal(total)
        return totals

    def paid_by_expenses(self, expense_ids: Sequence[UUID]) -> dict[UUID, Decimal]:
        """Décaissé par dépense, hors paiements annulés et annulations (ADR 0053)."""
        if not expense_ids:
            return {}
        stmt = (
            select(Payment.expense_id, func.coalesce(func.sum(Payment.amount), 0))
            .where(
                Payment.company_id == self.ctx.company_id,
                Payment.expense_id.in_(list(expense_ids)),
                Payment.direction == "outflow",
                *_counts_as_cash(),
            )
            .group_by(Payment.expense_id)
        )
        return {row[0]: Decimal(row[1]) for row in self.session.execute(stmt)}

    def daily_cash(
        self, *, period_from: datetime, period_to: datetime, timezone: str
    ) -> Sequence[Row[tuple[date, str, Decimal]]]:
        """Série jour × sens, dans le fuseau de l'entreprise, hors compensations et annulations.

        Le jour est celui que le gérant a vécu : `paid_at` est en UTC, la caisse
        ferme à l'heure locale. Sans conversion, une vente de 23 h tomberait le
        lendemain.
        """
        day = func.date(func.timezone(timezone, Payment.paid_at)).label("day")
        stmt = (
            select(day, Payment.direction, func.coalesce(func.sum(Payment.amount), 0))
            .where(
                Payment.company_id == self.ctx.company_id,
                *_counts_as_cash(),
                Payment.paid_at >= period_from,
                Payment.paid_at <= period_to,
            )
            .group_by(day, Payment.direction)
            .order_by(day)
        )
        return self.session.execute(stmt).all()


class DebtRepository(TenantRepository[Debt]):
    model = Debt

    def for_sale(self, sale_id: UUID) -> Debt | None:
        """La dette née de cette vente, s'il y en a une.

        Une vente engendre au plus une dette : son solde impayé à la confirmation.
        """
        stmt = self._select().where(Debt.sale_id == sale_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def lock_for_sale(self, sale_id: UUID) -> None:
        """Verrouille la dette de cette vente, quel que soit son statut.

        Un règlement verrouille la dette, puis le trigger `pa_sale_rollup` la vente :
        qui touche aux deux doit les prendre dans cet ordre (ADR 0062).
        """
        self.session.execute(self._select().where(Debt.sale_id == sale_id).with_for_update())

    def statuses_by_sale_ids(self, sale_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Statut de la dette de chaque vente qui en porte une, en une requête."""
        if not sale_ids:
            return {}
        stmt = select(Debt.sale_id, Debt.status).where(
            Debt.company_id == self.ctx.company_id, Debt.sale_id.in_(sale_ids)
        )
        return {sale_id: status for sale_id, status in self.session.execute(stmt).all()}

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

    def open_balances_by_customer(self, customer_ids: Sequence[UUID]) -> dict[UUID, Decimal]:
        """Encours de chaque client du lot, même définition qu'`open_balance_for_customer`.

        Un client sans dette ouverte est absent du résultat.
        """
        if not customer_ids:
            return {}
        stmt = (
            select(Debt.customer_id, func.sum(Debt.balance))
            .where(
                Debt.company_id == self.ctx.company_id,
                Debt.customer_id.in_(list(customer_ids)),
                Debt.status.in_(OPEN_STATUSES),
            )
            .group_by(Debt.customer_id)
        )
        return {
            customer_id: Decimal(balance)
            for customer_id, balance in self.session.execute(stmt).all()
            if customer_id is not None
        }

    def get_for_update(self, debt_id: UUID) -> Debt | None:
        """Dette du tenant, verrouillée pour la durée de la transaction.

        Le trigger `pa_check` prend le même verrou avant de comparer l'affectation
        au solde ; l'avancer ici ne change pas l'autorité, il permet seulement au
        refus applicatif de nommer le bon chiffre.
        """
        stmt = self._select().where(Debt.id == debt_id).with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def _filters(
        self,
        *,
        party_type: str | None,
        status: str | None,
        overdue_on: date | None,
        customer_id: UUID | None = None,
        supplier_id: UUID | None = None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if customer_id is not None:
            conditions.append(Debt.customer_id == customer_id)
        if supplier_id is not None:
            conditions.append(Debt.supplier_id == supplier_id)
        if party_type is not None:
            conditions.append(Debt.party_type == party_type)
        if status is not None:
            conditions.append(Debt.status == status)
        if overdue_on is not None:
            conditions.append(Debt.due_date.is_not(None))
            conditions.append(Debt.due_date < overdue_on)
            conditions.append(Debt.status.in_(OPEN_STATUSES))
        return conditions

    def count_filtered(
        self,
        *,
        party_type: str | None = None,
        status: str | None = None,
        overdue_on: date | None = None,
        customer_id: UUID | None = None,
        supplier_id: UUID | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Debt)
            .where(Debt.company_id == self.ctx.company_id)
            .where(
                *self._filters(
                    party_type=party_type,
                    status=status,
                    overdue_on=overdue_on,
                    customer_id=customer_id,
                    supplier_id=supplier_id,
                )
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def page_filtered(
        self,
        *,
        page: int,
        page_size: int,
        party_type: str | None = None,
        status: str | None = None,
        overdue_on: date | None = None,
        customer_id: UUID | None = None,
        supplier_id: UUID | None = None,
    ) -> Sequence[Debt]:
        stmt = (
            self._select()
            .where(
                *self._filters(
                    party_type=party_type,
                    status=status,
                    overdue_on=overdue_on,
                    customer_id=customer_id,
                    supplier_id=supplier_id,
                )
            )
            .order_by(Debt.due_date.asc().nullslast(), Debt.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def due_on_or_before(self, reference: date, *, limit: int) -> Sequence[Debt]:
        """Dettes encore ouvertes dont l'échéance est atteinte ou dépassée.

        `<=` et non `<` : une dette due aujourd'hui est due aujourd'hui. Le filtre
        `overdue_on` existant sert un autre besoin — lister ce qui est **en retard** —
        et les deux ne se confondent pas.

        Bornée : un balayage nocturne ne doit pas construire dix mille alertes d'un
        coup sur une entreprise qui découvre la fonctionnalité.
        """
        stmt = (
            self._select()
            .where(
                Debt.due_date.is_not(None),
                Debt.due_date <= reference,
                Debt.status.in_(OPEN_STATUSES),
            )
            .order_by(Debt.due_date.asc(), Debt.id.asc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def open_totals_by_party(self) -> dict[str, Decimal]:
        """Créances clients et dettes fournisseurs encore ouvertes, à l'instant t.

        Sans borne de période : un encours est un état, pas un flux. Le restreindre
        à une plage donnerait un chiffre que personne ne peut recouvrer.
        """
        stmt = (
            select(Debt.party_type, func.coalesce(func.sum(Debt.balance), 0))
            .where(
                Debt.company_id == self.ctx.company_id,
                Debt.status.in_(OPEN_STATUSES),
            )
            .group_by(Debt.party_type)
        )
        totals = {"customer": Decimal("0"), "supplier": Decimal("0")}
        for party_type, total in self.session.execute(stmt):
            totals[party_type] = Decimal(total)
        return totals


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

    def for_payment(self, payment_id: UUID) -> Sequence[PaymentAllocation]:
        """Affectations d'un versement, dans l'ordre où elles ont été écrites."""
        stmt = (
            self._select()
            .where(PaymentAllocation.payment_id == payment_id)
            .order_by(PaymentAllocation.created_at.asc(), PaymentAllocation.id.asc())
        )
        return self.session.execute(stmt).scalars().all()

    def for_payments(self, payment_ids: Sequence[UUID]) -> Sequence[PaymentAllocation]:
        """Affectations d'un lot de versements, en une requête (pas de N+1)."""
        if not payment_ids:
            return []
        stmt = (
            self._select()
            .where(PaymentAllocation.payment_id.in_(payment_ids))
            .order_by(PaymentAllocation.created_at.asc(), PaymentAllocation.id.asc())
        )
        return self.session.execute(stmt).scalars().all()

    def for_debts(self, debt_ids: Sequence[UUID]) -> Sequence[PaymentAllocation]:
        """Affectations reçues par un lot de dettes, en une requête."""
        if not debt_ids:
            return []
        stmt = (
            self._select()
            .where(PaymentAllocation.debt_id.in_(debt_ids))
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
