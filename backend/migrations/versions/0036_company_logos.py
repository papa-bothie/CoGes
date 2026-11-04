"""Logo de l'entreprise (prompt 35, bloc L, ADR 0111).

`company_logos` : une ligne par entreprise, le logo **ré-encodé** en PNG par l'API
(512 px de côté au plus, métadonnées retirées). Dans PostgreSQL pour être sauvegardé
par la sauvegarde chiffrée existante (ADR 0084) sans rien ajouter ; dans une table à
part, et non une colonne de `companies`, parce que `companies` est relue à presque
chaque requête et lue colonne par colonne par `coges_app_platform` (ADR 0089).

- RLS FORCE, politique tenant habituelle (T37), FK composite vers `users` (T5).
- `coges_app` n'a pas de DELETE : « Retirer » remet `png` et ses colonnes à `NULL`
  (l'image disparaît vraiment, la ligne reste). Les colonnes vont ensemble.
- `coges_analytics` n'en a pas besoin : ses privilèges par défaut sont repris.

Ajout seul, rétrocompatible (ADR 0083).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYTICS_ROLE = "coges_analytics"

#: Bornes en base, au-dessus de ce que l'API produit (512 px, quelques dizaines de Ko).
MAX_SIDE = 512
MAX_BYTES = 262_144


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE company_logos (
          company_id  uuid PRIMARY KEY REFERENCES companies (id) ON DELETE RESTRICT,
          png         bytea,
          sha256      char(64),
          width       integer,
          height      integer,
          byte_size   integer,
          updated_by  uuid NOT NULL,
          created_at  timestamptz NOT NULL DEFAULT now(),
          updated_at  timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT company_logos_updated_by_fk FOREIGN KEY (company_id, updated_by)
            REFERENCES users (company_id, id),
          -- Une image complète, ou rien du tout (logo retiré).
          CONSTRAINT company_logos_all_or_nothing CHECK (
            (png IS NULL AND sha256 IS NULL AND width IS NULL AND height IS NULL
             AND byte_size IS NULL)
            OR (png IS NOT NULL AND sha256 IS NOT NULL AND width IS NOT NULL
                AND height IS NOT NULL AND byte_size IS NOT NULL)
          ),
          CONSTRAINT company_logos_png_signature CHECK (
            png IS NULL OR substring(png FROM 1 FOR 8) = '\\x89504e470d0a1a0a'::bytea
          ),
          CONSTRAINT company_logos_dimensions CHECK (
            width IS NULL OR (width BETWEEN 1 AND {MAX_SIDE} AND height BETWEEN 1 AND {MAX_SIDE})
          ),
          CONSTRAINT company_logos_size CHECK (
            byte_size IS NULL OR (byte_size = octet_length(png) AND byte_size <= {MAX_BYTES})
          )
        )
        """
    )
    op.execute(
        "CREATE TRIGGER company_logos_set_updated_at BEFORE UPDATE ON company_logos "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute("ALTER TABLE company_logos ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE company_logos FORCE  ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY company_logos_tenant ON company_logos
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )
    op.execute(f"REVOKE ALL ON company_logos FROM {ANALYTICS_ROLE}")


def downgrade() -> None:
    op.execute("DROP TABLE company_logos")
