"""Formulaires courts du lot 1 de la phase 15 : unités, Wave et Orange Money, raisons de stock.

**1. Deux unités de plus** (ADR 0066) : `sac` et `bouteille`, comme le commerçant compte
son riz et son huile. La contrainte `products_unit_check` est remplacée.

**2. Wave et Orange Money** (ADR 0068) : deux valeurs de `pay_method`. `mobile_money`
reste valable pour les paiements déjà saisis et pour l'API ; le front ne le propose plus.
Une valeur d'ENUM ne se retire pas : la descente recrée le type, après avoir ramené les
paiements Wave et Orange Money à `mobile_money`.

**3. Raisons de correction en liste fermée** (ADR 0067) : `inventory_movements.reason_code`.
Une perte (`loss`) est abîmée, périmée, perdue ou volée, ou prise pour la maison ; un
ajustement (`adjustment`) est une erreur de comptage, un article retrouvé ou un cadeau du
fournisseur, ces deux derniers toujours en plus. `inv_reason_coherent` refuse une raison
qui ne va pas avec le type ou le sens. La raison reste nulle sur les mouvements d'avant
(motif écrit) et sur les inverses (ADR 0017) : l'API seule l'exige à la saisie.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNITS_BEFORE = ("piece", "kg", "litre", "carton", "metre", "paquet")
_UNITS_AFTER = (*_UNITS_BEFORE, "sac", "bouteille")

_METHODS_BEFORE = ("cash", "mobile_money", "bank_transfer", "card", "cheque", "offset")

_LOSS_REASONS = ("damaged", "expired", "lost_or_stolen", "home_use")
_ADJUSTMENT_REASONS = ("count_error", "found", "supplier_gift")


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _unit_check(units: Sequence[str]) -> None:
    op.execute("ALTER TABLE products DROP CONSTRAINT products_unit_check")
    op.execute(
        f"ALTER TABLE products ADD CONSTRAINT products_unit_check "
        f"CHECK (unit IN ({_quoted(units)}))"
    )


def upgrade() -> None:
    _unit_check(_UNITS_AFTER)

    op.execute("ALTER TYPE pay_method ADD VALUE IF NOT EXISTS 'wave'")
    op.execute("ALTER TYPE pay_method ADD VALUE IF NOT EXISTS 'orange_money'")

    op.execute(
        f"CREATE TYPE stock_reason AS ENUM ({_quoted((*_LOSS_REASONS, *_ADJUSTMENT_REASONS))})"
    )
    op.execute("ALTER TABLE inventory_movements ADD COLUMN reason_code stock_reason")
    op.execute(
        f"""
        ALTER TABLE inventory_movements ADD CONSTRAINT inv_reason_coherent CHECK (
            reason_code IS NULL
            OR (type = 'loss' AND reason_code IN ({_quoted(_LOSS_REASONS)}))
            OR (type = 'adjustment' AND reason_code = 'count_error')
            OR (type = 'adjustment' AND reason_code IN ('found', 'supplier_gift')
                AND qty_delta > 0)
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE inventory_movements DROP CONSTRAINT inv_reason_coherent")
    op.execute("ALTER TABLE inventory_movements DROP COLUMN reason_code")
    op.execute("DROP TYPE stock_reason")

    # Les paiements sont en append-only et sous RLS FORCE : la conversion de type
    # réécrit la colonne sans passer par les triggers ni par les politiques.
    op.execute("ALTER TYPE pay_method RENAME TO pay_method_0015")
    op.execute(f"CREATE TYPE pay_method AS ENUM ({_quoted(_METHODS_BEFORE)})")
    op.execute(
        """
        ALTER TABLE payments ALTER COLUMN method TYPE pay_method USING (
            CASE WHEN method::text IN ('wave', 'orange_money') THEN 'mobile_money'
                 ELSE method::text END
        )::pay_method
        """
    )
    op.execute("DROP TYPE pay_method_0015")

    # Un sac ou une bouteille redevient une pièce.
    op.execute("ALTER TABLE products DISABLE TRIGGER USER")
    op.execute("ALTER TABLE products NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE products SET unit = 'piece' WHERE unit IN ('sac', 'bouteille');
        """
    )
    op.execute("ALTER TABLE products FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE products ENABLE TRIGGER USER")
    _unit_check(_UNITS_BEFORE)
