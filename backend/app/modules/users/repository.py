"""Accès aux données du module Users."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, func, select, text

from app.core.repository import TenantRepository
from app.modules.users.models import User


class UserRepository(TenantRepository[User]):
    """Hérite du filtre tenant : aucune requête ne peut s'en passer."""

    model = User

    def _live(self) -> Select[tuple[User]]:
        """Base de toute lecture : filtre tenant + exclusion des suppressions logiques."""
        return self._select().where(User.deleted_at.is_(None))

    def get_live(self, user_id: UUID) -> User | None:
        """Utilisateur non supprimé du tenant courant."""
        return self.session.execute(self._live().where(User.id == user_id)).scalar_one_or_none()

    def get_by_email(self, email: str) -> User | None:
        """Unicité de l'e-mail **par entreprise** (`users_email_uq`)."""
        return self.session.execute(self._live().where(User.email == email)).scalar_one_or_none()

    def count_live(self) -> int:
        stmt = (
            select(func.count())
            .select_from(User)
            .where(User.company_id == self.ctx.company_id, User.deleted_at.is_(None))
        )
        return int(self.session.execute(stmt).scalar_one())

    def page_live(self, *, page: int, page_size: int) -> Sequence[User]:
        stmt = (
            self._live()
            .order_by(User.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return self.session.execute(stmt).scalars().all()

    def active_ids(self, user_ids: Sequence[UUID]) -> list[UUID]:
        """Identifiants encore actifs parmi ceux fournis, dans l'ordre d'entrée."""
        stmt = self._live().where(User.id.in_(list(user_ids)), User.is_active.is_(True))
        found = {row for row in self.session.execute(stmt.with_only_columns(User.id)).scalars()}
        return [user_id for user_id in dict.fromkeys(user_ids) if user_id in found]

    def names_by_id(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Noms des comptes, **supprimés compris** : un auteur d'audit reste nommé."""
        stmt = self._select().where(User.id.in_(list(user_ids)))
        rows = self.session.execute(stmt.with_only_columns(User.id, User.full_name)).all()
        return {row[0]: row[1] for row in rows}

    def lock_manager_guard(self) -> None:
        """Verrou transactionnel propre à l'entreprise, pour la garde du dernier gérant.

        Deux gérants qui se désactivent mutuellement comptent chacun l'autre comme
        « encore actif » s'ils lisent en même temps : sans point de rendez-vous, les deux
        passent (ADR 0054). Ce verrou consultatif sérialise **toutes** les voies qui
        retirent un gérant, pour une entreprise et elle seule ; il est libéré au COMMIT ou
        au ROLLBACK. La lecture qui suit, en READ COMMITTED, voit donc ce que l'autre
        transaction vient de valider.
        """
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"coges:last_manager:{self.ctx.company_id}"},
        )
