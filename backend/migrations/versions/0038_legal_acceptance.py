"""Acceptation des textes légaux (prompt 36, ADR 0117).

* `users.legal_accepted_version` : la version des conditions et de la politique de
  confidentialité que la personne a acceptée (`app/core/legal.py`), `NULL` tant qu'elle
  n'a rien accepté ;
* `users.legal_accepted_at` : le moment de cette acceptation ;
* `users_legal_acceptance_coherent` : les deux ensemble, ou aucun.

Ajout seul (ADR 0083) : l'image précédente ignore ces colonnes et continue de marcher.
Les comptes existants restent à `NULL` : ils accepteront à leur prochaine connexion.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN legal_accepted_version text")
    op.execute("ALTER TABLE users ADD COLUMN legal_accepted_at timestamptz")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_legal_acceptance_coherent "
        "CHECK ((legal_accepted_version IS NULL) = (legal_accepted_at IS NULL))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT users_legal_acceptance_coherent")
    op.execute("ALTER TABLE users DROP COLUMN legal_accepted_at")
    op.execute("ALTER TABLE users DROP COLUMN legal_accepted_version")
