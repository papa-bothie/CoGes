"""Correctifs de la revue de code, partie 2 (prompt 21, ADR 0088).

* **P2.1** — `users_revoke_sessions` : un mot de passe changé, un compte désactivé ou
  supprimé révoque **en base** toutes les sessions de la personne. Le module Users ne
  peut pas appeler Auth (Auth dépend de lui) : la règle descend en base, sur le
  précédent de l'ADR 0014. Une connexion réussie, qui ne touche que `last_login_at`,
  ne déclenche rien.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _revoke_sessions_on_access_change()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS users_revoke_sessions ON users")
    op.execute("DROP FUNCTION IF EXISTS users_revoke_sessions()")


def _revoke_sessions_on_access_change() -> None:
    # SECURITY INVOKER : `coges_app` révoque déjà des sessions (rotation, déconnexion),
    # sous la RLS de l'entreprise du contexte.
    op.execute(
        """
        CREATE FUNCTION users_revoke_sessions() RETURNS trigger AS $$
        BEGIN
           UPDATE auth_sessions
              SET revoked_at = now()
            WHERE company_id = NEW.company_id
              AND user_id = NEW.id
              AND revoked_at IS NULL;
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER users_revoke_sessions
        AFTER UPDATE OF password_hash, is_active, deleted_at ON users
        FOR EACH ROW
        WHEN (OLD.password_hash IS DISTINCT FROM NEW.password_hash
              OR (OLD.is_active AND NOT NEW.is_active)
              OR (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL))
        EXECUTE FUNCTION users_revoke_sessions()
        """
    )
