"""Exports PDF pour le comptable (prompt 35, bloc X, ADR 0114).

La file d'exports existante (révision 0013, ADR 0041) produit aussi des PDF : les ventes
d'une période et le journal de caisse, qui peuvent être longs, passent par le worker et
arrivent dans Réglages → Fichiers comme l'export Excel des ventes.

- `export_format` gagne `pdf` ;
- `export_files.kind` admet `cash` (journal de caisse) en plus de `sales`.

Ajout seul, rétrocompatible (ADR 0083). `downgrade` : les lignes PDF ou de caisse sont
retirées (elles n'existaient pas avant), puis le type est recréé sans `pdf`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "export_files"


def upgrade() -> None:
    op.execute("ALTER TYPE export_format ADD VALUE IF NOT EXISTS 'pdf'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT export_files_kind_check")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT export_files_kind_check "
        "CHECK (kind IN ('sales', 'cash'))"
    )


def downgrade() -> None:
    # `coges_app` n'a pas de DELETE et la table est sous RLS FORCE : le propriétaire lève
    # FORCE le temps de retirer ce que cette révision a rendu possible.
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM {TABLE} WHERE format::text = 'pdf' OR kind <> 'sales'")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT export_files_kind_check")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT export_files_kind_check CHECK (kind IN ('sales'))"
    )
    op.execute("ALTER TYPE export_format RENAME TO export_format_0037")
    op.execute("CREATE TYPE export_format AS ENUM ('csv', 'xlsx')")
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN format TYPE export_format "
        "USING (format::text)::export_format"
    )
    op.execute("DROP TYPE export_format_0037")
