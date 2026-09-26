"""Fichiers d'export produits par le worker et servis par l'API (ADR 0041).

Un export volumineux est une tâche worker (Architecture, « Où s'exécute quoi ») ; le
worker n'appelle jamais Vercel (Diagramme 2, `B⇸A`) : il écrit son résultat **en
base**, et l'API le sert. Ce résultat vit dans `export_files`, table absente du § 8 —
écart assumé et consigné dans l'ADR 0041.

- **Plafond** : `content` ne dépasse pas 10 Mo (`CHECK`). Un export plus lourd échoue
  en `failed` au lieu de gonfler une base dont l'offre gratuite plafonne à 0,5 Go.
- **Durée de vie** : 24 h. La purge ne supprime rien — `coges_app` n'a pas `DELETE` et
  n'en reçoit pas : elle passe `content` à NULL et `status` à `expired`. La ligne reste
  la trace de ce qui a été exporté, par qui, quand.
- **Cohérence du statut** : un fichier `ready` a un contenu, un fichier `expired`,
  `pending` ou `failed` n'en a pas (`CHECK`).
- **Isolation** : FK composite vers `users`, RLS FORCE à la forme `NULLIF` (ADR 0003).

Privilèges : ceux par défaut de la 0001 (SELECT, INSERT, UPDATE pour `coges_app`),
sans DELETE — T36 est inchangé.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "export_files"

#: 10 Mo. Au-delà, l'export échoue proprement au lieu de remplir la base.
MAX_CONTENT_BYTES = 10 * 1024 * 1024


def upgrade() -> None:
    op.execute("CREATE TYPE export_status AS ENUM ('pending', 'ready', 'failed', 'expired')")
    op.execute("CREATE TYPE export_format AS ENUM ('csv', 'xlsx')")
    op.execute(
        f"""
        CREATE TABLE {TABLE} (
          id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id    uuid NOT NULL REFERENCES companies (id),
          kind          text NOT NULL CHECK (kind IN ('sales')),
          format        export_format NOT NULL,
          params        jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          status        export_status NOT NULL DEFAULT 'pending',
          content       bytea,
          filename      text,
          row_count     integer CHECK (row_count >= 0),
          error         text,
          requested_by  uuid NOT NULL,
          created_at    timestamptz NOT NULL DEFAULT now(),
          updated_at    timestamptz NOT NULL DEFAULT now(),
          completed_at  timestamptz,
          expires_at    timestamptz NOT NULL DEFAULT now() + interval '24 hours',
          CONSTRAINT export_files_tenant_uq UNIQUE (company_id, id),
          CONSTRAINT export_files_requested_by_fk
            FOREIGN KEY (company_id, requested_by) REFERENCES users (company_id, id),
          CONSTRAINT export_files_size_chk
            CHECK (content IS NULL OR octet_length(content) <= {MAX_CONTENT_BYTES}),
          CONSTRAINT export_files_content_chk
            CHECK ((status = 'ready') = (content IS NOT NULL)),
          CONSTRAINT export_files_filename_chk
            CHECK (status <> 'ready' OR filename IS NOT NULL)
        )
        """
    )
    op.execute(f"CREATE INDEX export_files_company_created_idx ON {TABLE} (company_id, created_at)")
    op.execute(
        f"CREATE TRIGGER {TABLE}_set_updated_at BEFORE UPDATE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE  ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {TABLE}_tenant ON {TABLE}
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant ON {TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
    op.execute("DROP TYPE IF EXISTS export_format")
    op.execute("DROP TYPE IF EXISTS export_status")
