"""Accès aux données du module Customers."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, Integer, Select, cast, func, or_, select

from app.core.codes import number_pattern
from app.core.repository import TenantRepository
from app.core.search import code_matches, name_matches, relevance_order
from app.modules.customers.models import Customer


class CustomerRepository(TenantRepository[Customer]):
    """Hérite du filtre tenant : aucune requête ne peut s'en passer."""

    model = Customer

    def _live(self) -> Select[tuple[Customer]]:
        return self._select().where(Customer.deleted_at.is_(None))

    def _filters(
        self, *, search: str | None, exclude_ids: Sequence[UUID] = ()
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if search is not None:
            filters.append(
                or_(name_matches(Customer.name, search), code_matches((Customer.code,), search))
            )
        if exclude_ids:
            filters.append(Customer.id.not_in(list(exclude_ids)))
        return filters

    def get_live(self, customer_id: UUID) -> Customer | None:
        return self.session.execute(
            self._live().where(Customer.id == customer_id)
        ).scalar_one_or_none()

    def names_by_ids(self, customer_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Noms d'un lot de clients, en une requête plutôt qu'une par ligne."""
        if not customer_ids:
            return {}
        stmt = self._live().where(Customer.id.in_(list(customer_ids)))
        rows = self.session.execute(stmt.with_only_columns(Customer.id, Customer.name)).all()
        return {row[0]: row[1] for row in rows}

    def get_by_code(self, code: str) -> Customer | None:
        """Homonyme de code vivant (`customers_code_uq` est partielle)."""
        return self.session.execute(self._live().where(Customer.code == code)).scalar_one_or_none()

    def live_by_ids(self, customer_ids: Sequence[UUID]) -> Sequence[Customer]:
        """Clients vivants d'un lot d'identifiants, dans un ordre quelconque."""
        if not customer_ids:
            return []
        stmt = self._live().where(Customer.id.in_(list(customer_ids)))
        return self.session.execute(stmt).scalars().all()

    def count_live(self, *, search: str | None = None, exclude_ids: Sequence[UUID] = ()) -> int:
        stmt = (
            select(func.count())
            .select_from(Customer)
            .where(Customer.company_id == self.ctx.company_id, Customer.deleted_at.is_(None))
            .where(*self._filters(search=search, exclude_ids=exclude_ids))
        )
        return int(self.session.execute(stmt).scalar_one())

    def page_live(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        exclude_ids: Sequence[UUID] = (),
    ) -> Sequence[Customer]:
        stmt = (
            self._live()
            .where(*self._filters(search=search, exclude_ids=exclude_ids))
            .order_by(*relevance_order(Customer.name, (Customer.code,), search))
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def max_code_number(self, prefix: str) -> int:
        """Plus grand compteur déjà attribué **dans cette entreprise**.

        Les lignes supprimées comptent : leur code reste affiché dans l'historique
        des ventes, le réattribuer prêterait à confusion.
        """
        stmt = select(
            func.max(cast(func.substring(Customer.code, number_pattern(prefix)), Integer))
        ).where(Customer.company_id == self.ctx.company_id)
        return int(self.session.execute(stmt).scalar_one() or 0)
