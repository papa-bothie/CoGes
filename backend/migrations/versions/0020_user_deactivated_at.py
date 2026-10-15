"""Date de coupure d'un accès (ADR 0075, lot 3e-2 de la phase 15).

L'écran Personnes (maquette 24b) écrit « Accès coupé le 30 septembre ». `updated_at`
changerait à la moindre modification du compte : la date a sa propre colonne.

* `users.deactivated_at` : posée quand l'accès est coupé, effacée quand il est redonné ;
* `users_deactivated_coherent` : un compte actif n'a pas de date, un compte coupé en a
  une ;
* les comptes déjà coupés reprennent `deleted_at`, sinon `updated_at`.

`users` est sous RLS FORCE : FORCE est levé le temps de la seule mise à jour de données
(comme en révision 0019).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN deactivated_at timestamptz")
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE users
           SET deactivated_at = coalesce(deleted_at, updated_at)
         WHERE NOT is_active;
        """
    )
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_deactivated_coherent "
        "CHECK (is_active = (deactivated_at IS NULL))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT users_deactivated_coherent")
    op.execute("ALTER TABLE users DROP COLUMN deactivated_at")
