"""Coordonnées de la boutique, imprimées sur le reçu (ADR 0070, lot 3a de la phase 15).

Le reçu et la facture de la maquette v2 portent l'adresse, le téléphone, le NINEA, le RC
et un message de bas de reçu ; la fiche client rappelle une dette avec le numéro Wave de
la boutique. Six colonnes facultatives sur `companies`, bornées en longueur ; le
contenu reste libre (un NINEA ou un RC n'a pas de format unique au Sénégal). L'écran
« Ma boutique » arrive au lot 3e : d'ici là, `PATCH /companies/me` les règle.

Les privilèges de `coges_app` sur `companies` sont des privilèges de table (révision
0001) : les nouvelles colonnes en héritent, rien à accorder.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Colonne → longueur maximale, identique à `CompanyUpdate`.
SHOP_COLUMNS: dict[str, int] = {
    "address": 200,
    "phone": 30,
    "wave_number": 30,
    "ninea": 30,
    "rc": 40,
    "receipt_footer": 300,
}


def upgrade() -> None:
    for column, length in SHOP_COLUMNS.items():
        op.execute(f"ALTER TABLE companies ADD COLUMN {column} text")
        op.execute(
            f"ALTER TABLE companies ADD CONSTRAINT companies_{column}_length "
            f"CHECK ({column} IS NULL OR char_length({column}) BETWEEN 1 AND {length})"
        )


def downgrade() -> None:
    for column in SHOP_COLUMNS:
        op.execute(f"ALTER TABLE companies DROP CONSTRAINT companies_{column}_length")
        op.execute(f"ALTER TABLE companies DROP COLUMN {column}")
