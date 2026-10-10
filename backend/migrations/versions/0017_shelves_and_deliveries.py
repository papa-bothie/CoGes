"""Couleur des rayons et livraisons fournisseur (ADR 0071, lot 3b de la phase 15).

**1. Couleur d'un rayon** : `categories.color`, de 1 à 8 (la palette de la maquette v2,
écran 12), facultative ; vide, le front tire la couleur du nom.

**2. Livraison** : une livraison (`POST /inventory/deliveries`) écrit une entrée
`purchase_in` par article et ouvre la dette fournisseur qui la porte. Chaque entrée pointe
vers cette dette : `ref_type = 'supplier_debt'`, `ref_id` = la dette. C'est ce qui permet
de dire « Livraison de Grossiste Sandaga » sur la fiche d'un article et de regrouper les
livraisons d'un fournisseur. Écart assumé à la liste des `ref_type` du modèle V1.1 (§ 8.5),
consigné dans l'ADR 0071.

`inv_ref_idempotence` rendait unique le couple (`ref_type`, `ref_id`) : une livraison de
deux articles y violerait l'index. Il exclut désormais `supplier_debt`, dont l'unicité
porte sur (dette, article) : un article n'entre qu'une fois par livraison.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REF_TYPES_BEFORE = ("sale_item", "sale_return_item", "manual", "import", "initial")
_REF_TYPES_AFTER = (*_REF_TYPES_BEFORE, "supplier_debt")


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _ref_type_check(values: Sequence[str]) -> None:
    op.execute("ALTER TABLE inventory_movements DROP CONSTRAINT inventory_movements_ref_type_check")
    op.execute(
        "ALTER TABLE inventory_movements ADD CONSTRAINT inventory_movements_ref_type_check "
        f"CHECK (ref_type IN ({_quoted(values)}))"
    )


def upgrade() -> None:
    op.execute("ALTER TABLE categories ADD COLUMN color smallint")
    op.execute(
        "ALTER TABLE categories ADD CONSTRAINT categories_color_range "
        "CHECK (color IS NULL OR color BETWEEN 1 AND 8)"
    )

    _ref_type_check(_REF_TYPES_AFTER)
    op.execute("DROP INDEX inv_ref_idempotence")
    op.execute(
        """
        CREATE UNIQUE INDEX inv_ref_idempotence
           ON inventory_movements (company_id, ref_type, ref_id)
         WHERE ref_id IS NOT NULL AND reversal_of_movement_id IS NULL
           AND ref_type <> 'supplier_debt'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX inv_delivery_line_uq
           ON inventory_movements (company_id, ref_id, product_id)
         WHERE ref_type = 'supplier_debt' AND reversal_of_movement_id IS NULL
        """
    )


def downgrade() -> None:
    # Les entrées de livraison perdent leur lien : elles redeviennent des entrées sans
    # référence, comme une saisie manuelle d'avant la révision.
    op.execute("ALTER TABLE inventory_movements DISABLE TRIGGER USER")
    op.execute("ALTER TABLE inventory_movements NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE inventory_movements SET ref_type = NULL, ref_id = NULL
        WHERE ref_type = 'supplier_debt'
        """
    )
    op.execute("ALTER TABLE inventory_movements FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE inventory_movements ENABLE TRIGGER USER")

    op.execute("DROP INDEX inv_delivery_line_uq")
    op.execute("DROP INDEX inv_ref_idempotence")
    op.execute(
        """
        CREATE UNIQUE INDEX inv_ref_idempotence
           ON inventory_movements (company_id, ref_type, ref_id)
         WHERE ref_id IS NOT NULL AND reversal_of_movement_id IS NULL
        """
    )
    _ref_type_check(_REF_TYPES_BEFORE)

    op.execute("ALTER TABLE categories DROP CONSTRAINT categories_color_range")
    op.execute("ALTER TABLE categories DROP COLUMN color")
