"""Corriger une vente : la vente qui en remplace une autre (prompt 36, bloc R, ADR 0119).

« Corriger cette vente » annule une vente encaissée depuis moins de 10 minutes et ouvre
un brouillon identique. Ce brouillon dit quelle vente il corrige :

- `sales.corrects_sale_id` : la vente annulée qu'il remplace, `NULL` pour toute autre
  vente. Clé étrangère composite, comme toutes les références entre tables d'entreprise :
  une vente ne peut pas corriger celle d'une autre entreprise (barrière 1).
- `sales_corrects_sale_uq` : une vente n'est corrigée qu'une fois. Deux personnes qui
  appuient ensemble ne font jamais deux brouillons, même si le service laissait passer.
- `sales_corrects_other_sale` : une vente ne se corrige pas elle-même.

Ajout seul, rétrocompatible (ADR 0083) : l'ancienne API ignore la colonne.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE sales
          ADD COLUMN corrects_sale_id uuid,
          ADD CONSTRAINT sales_corrects_sale_fk
            FOREIGN KEY (company_id, corrects_sale_id) REFERENCES sales (company_id, id),
          ADD CONSTRAINT sales_corrects_other_sale CHECK (corrects_sale_id <> id)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX sales_corrects_sale_uq
            ON sales (company_id, corrects_sale_id)
         WHERE corrects_sale_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX sales_corrects_sale_uq")
    op.execute(
        """
        ALTER TABLE sales
          DROP CONSTRAINT sales_corrects_other_sale,
          DROP CONSTRAINT sales_corrects_sale_fk,
          DROP COLUMN corrects_sale_id
        """
    )
