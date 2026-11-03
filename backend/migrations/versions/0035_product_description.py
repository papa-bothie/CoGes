"""Description d'un article (prompt 34, bloc D, ADR 0108).

`products.description` : texte facultatif, 500 caractères au plus, `NULL` quand rien
n'est saisi. Ajout seul, rétrocompatible (ADR 0083).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE products
          ADD COLUMN description text
            CONSTRAINT products_description_length CHECK (char_length(description) <= 500)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN description")
