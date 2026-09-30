"""Accès aux données du module Auth."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from app.core.database import get_session_factory
from app.core.repository import TenantRepository
from app.modules.auth.models import AuthSession

#: Point P2 : la connexion doit lire `companies` et `users` **avant** tout contexte
#: tenant. `auth_lookup` appartient à `coges_auth` (NOLOGIN BYPASSRLS) et ne renvoie
#: que ces quatre colonnes, pour un seul couple (slug, e-mail). Voir ADR 0005.
_AUTH_LOOKUP = text(
    "SELECT company_id, user_id, password_hash, is_active "
    "FROM auth_lookup(CAST(:slug AS citext), CAST(:email AS citext))"
)


@dataclass(frozen=True, slots=True)
class AuthIdentity:
    """Résultat minimal de la recherche d'identité."""

    company_id: UUID
    user_id: UUID
    password_hash: str
    is_active: bool


@contextmanager
def auth_lookup_transaction() -> Iterator[Session]:
    """Transaction **sans contexte tenant**, réservée à `auth_lookup`.

    C'est la seule requête du projet qui s'exécute sans contexte, et elle ne le
    peut que parce que `auth_lookup` est une fonction `SECURITY DEFINER` au
    périmètre minimal (ADR 0005). Aucune autre lecture ne doit passer par ici : un
    test d'architecture vérifie que ce gestionnaire n'est utilisé que dans ce module.
    """
    session: Session = get_session_factory()()
    try:
        with session.begin():
            yield session
    finally:
        session.close()


def lookup_identity(session: Session, *, slug: str, email: str) -> AuthIdentity | None:
    """Traduit (slug, e-mail) en identité, hors contexte tenant."""
    row = session.execute(_AUTH_LOOKUP, {"slug": slug, "email": email}).one_or_none()
    if row is None:
        return None
    return AuthIdentity(
        company_id=row.company_id,
        user_id=row.user_id,
        password_hash=row.password_hash,
        is_active=row.is_active,
    )


class AuthSessionRepository(TenantRepository[AuthSession]):
    """Sessions de rafraîchissement du tenant courant."""

    model = AuthSession

    def get_by_token_hash(self, token_hash: str) -> AuthSession | None:
        stmt = self._select().where(AuthSession.token_hash == token_hash)
        return self.session.execute(stmt).scalar_one_or_none()

    def lock_by_token_hash(self, token_hash: str) -> AuthSession | None:
        """Lit la session **en la verrouillant** jusqu'au COMMIT.

        Deux rafraîchissements simultanés avec le même jeton se sérialisent : le
        second attend, puis relit la ligne avec `revoked_at` renseigné et échoue.
        Sans ce verrou, les deux pourraient tourner le jeton en parallèle et
        émettre deux sessions valides à partir d'un seul jeton.
        """
        stmt = self._select().where(AuthSession.token_hash == token_hash).with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def lock_by_id(self, session_id: UUID) -> AuthSession | None:
        """Lit une session par son identifiant, verrouillée jusqu'au COMMIT."""
        stmt = self._select().where(AuthSession.id == session_id).with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def revoke_family(self, family_id: UUID) -> int:
        """Révoque toutes les sessions d'une famille : réutilisation détectée."""
        statement = (
            update(AuthSession)
            .where(
                AuthSession.company_id == self.ctx.company_id,
                AuthSession.family_id == family_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        return int(self.session.execute(statement).rowcount or 0)  # type: ignore[attr-defined]

    def active_count_for_user(self, user_id: UUID) -> int:
        stmt = select(AuthSession.id).where(
            AuthSession.company_id == self.ctx.company_id,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        return len(list(self.session.execute(stmt).scalars().all()))
