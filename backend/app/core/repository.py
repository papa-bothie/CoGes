"""Repository de base — barrière 2 du Diagramme 8.

Un repository métier hérite de `TenantRepository` et ne construit **jamais** une
requête lui-même : il part toujours de `self._select()`, qui porte le filtre
`company_id`. Les écritures passent par `add()`, qui refuse une ligne rattachée à
une autre entreprise.

Cette barrière ne remplace pas la RLS : elle donne un message métier exploitable
là où PostgreSQL renverrait une violation de politique.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.database import IdentifiedTenantBase
from app.core.errors import TenantIsolationError
from app.core.tenancy import TenantContext

MAX_PAGE_SIZE = 100


class TenantRepository[ModelT: IdentifiedTenantBase]:
    """Accès aux données d'un seul tenant, celui du contexte."""

    model: type[ModelT]

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def _select(self) -> Select[tuple[ModelT]]:
        """Seul point de départ autorisé pour une requête de lecture."""
        return select(self.model).where(self.model.company_id == self.ctx.company_id)

    def get(self, entity_id: UUID) -> ModelT | None:
        """Renvoie l'entité du tenant courant, ou None — jamais celle d'un autre."""
        stmt = self._select().where(self.model.id == entity_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def count(self) -> int:
        """Nombre d'entités du tenant courant."""
        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.company_id == self.ctx.company_id)
        )
        return int(self.session.execute(stmt).scalar_one())

    def page(self, *, page: int = 1, page_size: int = 20) -> Sequence[ModelT]:
        """Pagination obligatoire sur toutes les listes."""
        if page < 1:
            raise ValueError("page doit être >= 1")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size doit être entre 1 et {MAX_PAGE_SIZE}")
        stmt = self._select().limit(page_size).offset((page - 1) * page_size)
        return self.session.execute(stmt).scalars().all()

    def add(self, entity: ModelT) -> ModelT:
        """Ajoute une entité après avoir imposé le `company_id` du contexte."""
        current: Any = getattr(entity, "company_id", None)
        if current is None:
            entity.company_id = self.ctx.company_id
        elif current != self.ctx.company_id:
            raise TenantIsolationError(
                details={"expected": str(self.ctx.company_id), "received": str(current)}
            )
        self.session.add(entity)
        return entity
