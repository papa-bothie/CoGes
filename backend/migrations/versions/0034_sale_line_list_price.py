"""Prix changé sur une ligne de vente (prompt 34, bloc P, ADR 0107).

`sale_items.unit_price` reste **le** prix de la ligne : celui que le client paie et
d'où la base tire le montant, la taxe et le total (colonnes générées inchangées).
Deux colonnes s'y ajoutent, sans rien retirer (ADR 0083) :

- `list_price` : le prix de la fiche, posé à l'ajout et refigé à la confirmation.
  `unit_price <> list_price` veut dire « prix changé à la caisse ». `NULL` pour les
  lignes écrites avant cette révision (aucun prix n'y a été changé).
- `price_reason` : motif facultatif du changement, 120 caractères au plus.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE sale_items
          ADD COLUMN list_price numeric(14,2)
            CONSTRAINT sale_items_list_price_positive CHECK (list_price >= 0),
          ADD COLUMN price_reason text
            CONSTRAINT sale_items_price_reason_length CHECK (char_length(price_reason) <= 120)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sale_items DROP COLUMN price_reason, DROP COLUMN list_price")
