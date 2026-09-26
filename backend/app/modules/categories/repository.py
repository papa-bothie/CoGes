"""Accès aux données du module Categories.

Requêtes filtrées par tenant, et rien d'autre : aucune règle métier ici. Toute
lecture part de `self._select()` (barrière 2, `app/core/repository.py`), qui porte
déjà le filtre `company_id`.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, literal, select
from sqlalchemy.orm import aliased

from app.core.repository import TenantRepository
from app.core.search import name_matches
from app.modules.categories.models import Category

#: Garde-fou de la remontée d'arbre. Le catalogue d'une PME n'a jamais 50 niveaux ;
#: la borne existe pour qu'une donnée corrompue produise une requête finie plutôt
#: qu'une récursion sans fin.
MAX_TREE_DEPTH = 50


class CategoryRepository(TenantRepository[Category]):
    """Hérite du filtre tenant : aucune requête ne peut s'en passer."""

    model = Category

    def _live(self) -> Select[tuple[Category]]:
        """Base de toute lecture : filtre tenant + exclusion des suppressions logiques."""
        return self._select().where(Category.deleted_at.is_(None))

    def _filters(self, *, search: str | None, parent_id: UUID | None) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if search is not None:
            conditions.append(name_matches(Category.name, search))
        if parent_id is not None:
            conditions.append(Category.parent_id == parent_id)
        return conditions

    def get_live(self, category_id: UUID) -> Category | None:
        """Catégorie non supprimée du tenant courant."""
        stmt = self._live().where(Category.id == category_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def live_names_by_ids(self, category_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Libellés vivants d'un lot de catégories, en une requête (pas de N+1)."""
        if not category_ids:
            return {}
        stmt = select(Category.id, Category.name).where(
            Category.company_id == self.ctx.company_id,
            Category.deleted_at.is_(None),
            Category.id.in_(category_ids),
        )
        return {row.id: row.name for row in self.session.execute(stmt)}

    def live_name_index(self) -> list[tuple[UUID, str, UUID | None]]:
        """(id, nom, parent) de toutes les catégories vivantes, pour résoudre des noms."""
        stmt = select(Category.id, Category.name, Category.parent_id).where(
            Category.company_id == self.ctx.company_id, Category.deleted_at.is_(None)
        )
        return [(row.id, row.name, row.parent_id) for row in self.session.execute(stmt)]

    def get_by_name(self, name: str, parent_id: UUID | None) -> Category | None:
        """Homonyme vivant sous le même parent (index `categories_name_uq`)."""
        stmt = self._live().where(Category.name == name)
        stmt = stmt.where(
            Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def count_live(self, *, search: str | None = None, parent_id: UUID | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(Category)
            .where(Category.company_id == self.ctx.company_id, Category.deleted_at.is_(None))
            .where(*self._filters(search=search, parent_id=parent_id))
        )
        return int(self.session.execute(stmt).scalar_one())

    def page_live(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        parent_id: UUID | None = None,
    ) -> Sequence[Category]:
        stmt = (
            self._live()
            .where(*self._filters(search=search, parent_id=parent_id))
            .order_by(Category.name)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def count_live_children(self, category_id: UUID) -> int:
        """Sous-catégories vivantes d'une catégorie."""
        stmt = (
            select(func.count())
            .select_from(Category)
            .where(
                Category.company_id == self.ctx.company_id,
                Category.parent_id == category_id,
                Category.deleted_at.is_(None),
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def self_and_ancestor_ids(self, category_id: UUID) -> list[UUID]:
        """La catégorie et toute sa lignée de parents, en une requête.

        Les catégories supprimées logiquement restent dans la chaîne : la structure
        de l'arbre ne dépend pas de leur visibilité, et un cycle passant par une
        branche supprimée resterait un cycle.
        """
        seed = (
            select(
                Category.id.label("id"),
                Category.parent_id.label("parent_id"),
                literal(1).label("depth"),
            )
            .where(Category.company_id == self.ctx.company_id, Category.id == category_id)
            .cte("category_ancestors", recursive=True)
        )
        parent = aliased(Category)
        chain = seed.union_all(
            select(parent.id, parent.parent_id, seed.c.depth + 1).where(
                parent.company_id == self.ctx.company_id,
                parent.id == seed.c.parent_id,
                seed.c.depth < MAX_TREE_DEPTH,
            )
        )
        return list(self.session.execute(select(chain.c.id)).scalars().all())
