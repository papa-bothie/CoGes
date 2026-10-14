"""Accès aux données du module Suppliers."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, Integer, Select, cast, func, or_, select

from app.core.codes import number_pattern
from app.core.repository import TenantRepository
from app.core.search import code_matches, name_matches, phone_matches, relevance_order
from app.modules.suppliers.models import Supplier


class SupplierRepository(TenantRepository[Supplier]):
    """Hérite du filtre tenant : aucune requête ne peut s'en passer."""

    model = Supplier

    def _live(self) -> Select[tuple[Supplier]]:
        return self._select().where(Supplier.deleted_at.is_(None))

    def _filters(self, *, search: str | None) -> list[ColumnElement[bool]]:
        if search is None:
            return []
        return [
            or_(
                name_matches(Supplier.name, search),
                code_matches((Supplier.code,), search),
                phone_matches(Supplier.phone, search),
            )
        ]

    def get_live(self, supplier_id: UUID) -> Supplier | None:
        return self.session.execute(
            self._live().where(Supplier.id == supplier_id)
        ).scalar_one_or_none()

    def names_by_ids(self, supplier_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Noms d'un lot de fournisseurs, en une requête plutôt qu'une par ligne."""
        if not supplier_ids:
            return {}
        stmt = self._live().where(Supplier.id.in_(list(supplier_ids)))
        rows = self.session.execute(stmt.with_only_columns(Supplier.id, Supplier.name)).all()
        return {row[0]: row[1] for row in rows}

    def get_by_code(self, code: str) -> Supplier | None:
        """Homonyme de code vivant (`suppliers_code_uq` est partielle)."""
        return self.session.execute(self._live().where(Supplier.code == code)).scalar_one_or_none()

    def count_live(self, *, search: str | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(Supplier)
            .where(Supplier.company_id == self.ctx.company_id, Supplier.deleted_at.is_(None))
            .where(*self._filters(search=search))
        )
        return int(self.session.execute(stmt).scalar_one())

    def page_live(
        self, *, page: int, page_size: int, search: str | None = None
    ) -> Sequence[Supplier]:
        stmt = (
            self._live()
            .where(*self._filters(search=search))
            .order_by(*relevance_order(Supplier.name, (Supplier.code,), search))
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
            func.max(cast(func.substring(Supplier.code, number_pattern(prefix)), Integer))
        ).where(Supplier.company_id == self.ctx.company_id)
        return int(self.session.execute(stmt).scalar_one() or 0)
