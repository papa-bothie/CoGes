"""Lecture seule de toute la base pour la sauvegarde externe (ADR 0084, prompt 19).

`coges_backup` est un rôle de **cluster** (créé par `deploy/sql/create_backup_role.sql`
sur Neon, par `deploy/postgres/init/01-roles.sql` en local et en CI) : LOGIN, BYPASSRLS,
sans aucun autre attribut. `pg_dump` en a besoin : toutes les tables de tenant sont en
FORCE ROW LEVEL SECURITY, et sans BYPASSRLS il ne verrait aucune ligne. C'est la seule
exception à la règle « aucun rôle connectable ne franchit la RLS » (T36), bornée ici :

* `SELECT` sur toutes les tables et séquences du schéma `public`, et rien d'autre ;
* les mêmes droits sur les tables créées plus tard par `coges_owner` (privilèges par
  défaut), partitions d'audit comprises (`ensure_audit_partition` appartient à
  `coges_owner`) ;
* aucun `EXECUTE` sur les fonctions privilégiées, aucun droit d'écriture (T36 le vérifie).

Son DSN ne vit que dans le secret GitHub `BACKUP_DATABASE_URL` du workflow de
sauvegarde : jamais sur le VPS, et l'API refuse de démarrer sous un rôle BYPASSRLS
(garde-fou 1, ADR 0042).

Prérequis : le rôle doit exister avant cette révision (`create_backup_role.sql`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKUP_ROLE = "coges_backup"

_REQUIRE_ROLE = f"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{BACKUP_ROLE}') THEN
    RAISE EXCEPTION 'rôle {BACKUP_ROLE} absent : lancer deploy/sql/create_backup_role.sql '
                    'avant cette migration (ADR 0084)';
  END IF;
END
$$
"""


def upgrade() -> None:
    op.execute(_REQUIRE_ROLE)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {BACKUP_ROLE}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {BACKUP_ROLE}")
    op.execute(f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO {BACKUP_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {BACKUP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO {BACKUP_ROLE}"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON SEQUENCES FROM {BACKUP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM {BACKUP_ROLE}"
    )
    op.execute(f"REVOKE SELECT ON ALL SEQUENCES IN SCHEMA public FROM {BACKUP_ROLE}")
    op.execute(f"REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM {BACKUP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {BACKUP_ROLE}")
