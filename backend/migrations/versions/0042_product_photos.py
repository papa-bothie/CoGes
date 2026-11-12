"""Photo d'un article, stockée chez Cloudinary (prompt 36, bloc I, ADR 0121).

Quatre colonnes facultatives sur `products`, qui disent où lire l'image chez Cloudinary :
`photo_public_id` (dossier de l'entreprise puis identifiant aléatoire, jamais le nom de
l'article), `photo_version` (change à chaque nouvelle image : le navigateur ne montre pas
l'ancienne), `photo_width` et `photo_height` (la place se réserve avant le chargement).
Les quatre ensemble, ou aucune : retirer la photo ou supprimer l'article les remet à `NULL`.

Les octets ne sont pas en base, donc pas dans la sauvegarde chiffrée (ADR 0084) : voir
`docs/runbooks/photos.md`. Ajout seul, rétrocompatible (ADR 0083).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE products
          ADD COLUMN photo_public_id text,
          ADD COLUMN photo_version   bigint,
          ADD COLUMN photo_width     integer,
          ADD COLUMN photo_height    integer,
          ADD CONSTRAINT products_photo_all_or_nothing CHECK (
            (photo_public_id IS NULL AND photo_version IS NULL
             AND photo_width IS NULL AND photo_height IS NULL)
            OR (photo_public_id IS NOT NULL AND photo_version IS NOT NULL
                AND photo_width IS NOT NULL AND photo_height IS NOT NULL)
          ),
          ADD CONSTRAINT products_photo_public_id CHECK (
            photo_public_id ~ '^[A-Za-z0-9_/-]{1,200}$'
          ),
          ADD CONSTRAINT products_photo_dimensions CHECK (
            photo_width BETWEEN 1 AND 1600 AND photo_height BETWEEN 1 AND 1600
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE products
          DROP CONSTRAINT products_photo_dimensions,
          DROP CONSTRAINT products_photo_public_id,
          DROP CONSTRAINT products_photo_all_or_nothing,
          DROP COLUMN photo_height,
          DROP COLUMN photo_width,
          DROP COLUMN photo_version,
          DROP COLUMN photo_public_id
        """
    )
