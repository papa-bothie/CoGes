"""Adresse d'un fournisseur (ADR 0072, lot 3c de la phase 15).

La fiche fournisseur de la maquette v2 (écran 16) affiche son adresse sous son nom
(« Marché Sandaga, Dakar »). Une colonne facultative sur `suppliers`, bornée en
longueur comme l'adresse de la boutique (révision 0016) ; on la saisit dans
« Modifier », jamais à la création, qui reste le nom et le téléphone.

Les privilèges de `coges_app` sur `suppliers` sont des privilèges de table (révision
0001) : la nouvelle colonne en hérite, rien à accorder.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Identique à `SupplierUpdate.address` et à l'adresse de la boutique.
ADDRESS_MAX_LENGTH = 200


def upgrade() -> None:
    op.execute("ALTER TABLE suppliers ADD COLUMN address text")
    op.execute(
        "ALTER TABLE suppliers ADD CONSTRAINT suppliers_address_length "
        f"CHECK (address IS NULL OR char_length(address) BETWEEN 1 AND {ADDRESS_MAX_LENGTH})"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE suppliers DROP CONSTRAINT suppliers_address_length")
    op.execute("ALTER TABLE suppliers DROP COLUMN address")
