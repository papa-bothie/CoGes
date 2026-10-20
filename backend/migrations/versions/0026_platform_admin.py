"""Administration de la plateforme, lot 1 : comptes, statut des entreprises (ADR 0089).

Trois choses, et une seule règle : le rôle de l'administration ne peut **pas**, par
construction, lire une vente, un stock, un paiement ou un article.

- **`coges_app_platform`** (créé hors migration : `01-roles.sql` en local et en CI,
  `deploy/sql/create_platform_role.sql` sur Neon) : LOGIN, NOBYPASSRLS. Il ne reçoit que
  des GRANT **colonne par colonne** sur `companies`, `users`, `roles`, `user_roles` et
  `audit_logs` (deux colonnes : de quoi dater la dernière activité, jamais le `diff`), et
  des politiques RLS qui ne nomment que lui. Une politique n'ouvre rien sans GRANT : la
  barrière est le GRANT, et `tests/architecture/test_platform_role_grants.py` énumère
  toutes les tables pour le prouver.
- **`companies.status`** (`trial`, `active`, `suspended`) : `active` pour l'existant et,
  jusqu'au lot 24 (abonnements), pour les nouvelles. Une entreprise suspendue ne se
  connecte plus et ses jetons cessent de servir à la requête suivante (`core/deps.py`).
- **Trois tables de plateforme** sans `company_id`, donc hors RLS (comme `permissions`) :
  `platform_users`, `platform_auth_sessions`, `platform_audit_logs`. `coges_app` et
  `coges_analytics` n'y ont aucun droit ; `coges_backup` les lit (sauvegarde complète).
  Le journal plateforme est append-only : SELECT et INSERT, ni UPDATE ni DELETE.

Prérequis : le rôle doit exister avant cette révision.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLATFORM_ROLE = "coges_app_platform"
APP_ROLE = "coges_app"
ANALYTICS_ROLE = "coges_analytics"

PLATFORM_TABLES = ("platform_users", "platform_auth_sessions", "platform_audit_logs")

#: Colonnes lisibles par l'administration, table par table. Rien d'autre.
PLATFORM_READ_COLUMNS: dict[str, tuple[str, ...]] = {
    "companies": ("id", "name", "slug", "status", "created_at", "deleted_at"),
    "users": (
        "id",
        "company_id",
        "full_name",
        "email",
        "phone",
        "is_active",
        "last_login_at",
        "deleted_at",
    ),
    "roles": ("id", "company_id", "name", "description"),
    "user_roles": ("user_id", "role_id", "company_id"),
    "audit_logs": ("company_id", "occurred_at"),
}

_REQUIRE_ROLE = f"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
    RAISE EXCEPTION 'rôle {PLATFORM_ROLE} absent : lancer deploy/sql/create_platform_role.sql '
                    'avant cette migration (ADR 0089)';
  END IF;
END
$$
"""


def upgrade() -> None:
    op.execute(_REQUIRE_ROLE)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PLATFORM_ROLE}")

    # --- Statut des entreprises ---
    op.execute("CREATE TYPE company_status AS ENUM ('trial', 'active', 'suspended')")
    op.execute("ALTER TABLE companies ADD COLUMN status company_status NOT NULL DEFAULT 'active'")
    # `coges_app` a UPDATE sur toute la table (réglages de la boutique) : sans cette
    # garde, un gérant suspendu qui garderait un chemin d'écriture pourrait se
    # réactiver. Le statut ne change que par l'administration, ou par une migration.
    op.execute(
        f"""
        CREATE FUNCTION companies_status_guard() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        BEGIN
          IF NEW.status IS DISTINCT FROM OLD.status
             AND current_user NOT IN ('{PLATFORM_ROLE}', 'coges_owner') THEN
            RAISE EXCEPTION 'le statut d''une entreprise ne change que par l''administration'
              USING ERRCODE = 'CG006';
          END IF;
          RETURN NEW;
        END
        $fn$
        """
    )
    op.execute(
        """
        CREATE TRIGGER companies_status_guard BEFORE UPDATE OF status ON companies
          FOR EACH ROW EXECUTE FUNCTION companies_status_guard()
        """
    )

    # --- Comptes de la plateforme ---
    op.execute("CREATE TYPE platform_role AS ENUM ('administrator', 'support')")
    op.execute(
        """
        CREATE TABLE platform_users (
          id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          email          citext NOT NULL UNIQUE
                         CHECK (email ~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'),
          password_hash  text NOT NULL,
          display_name   text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 120),
          role           platform_role NOT NULL,
          is_active      boolean NOT NULL DEFAULT true,
          last_login_at  timestamptz,
          created_at     timestamptz NOT NULL DEFAULT now(),
          updated_at     timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER platform_users_set_updated_at BEFORE UPDATE ON platform_users
          FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TABLE platform_auth_sessions (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          platform_user_id  uuid NOT NULL REFERENCES platform_users (id) ON DELETE CASCADE,
          token_hash        text NOT NULL UNIQUE,
          family_id         uuid NOT NULL,
          issued_at         timestamptz NOT NULL DEFAULT now(),
          expires_at        timestamptz NOT NULL,
          revoked_at        timestamptz,
          replaced_by       uuid REFERENCES platform_auth_sessions (id),
          user_agent        text,
          ip_address        inet
        )
        """
    )
    op.execute(
        "CREATE INDEX platform_auth_sessions_family_idx ON platform_auth_sessions (family_id)"
    )
    # Mot de passe changé ou compte désactivé : toutes ses sessions tombent (ADR 0088).
    op.execute(
        """
        CREATE FUNCTION platform_users_revoke_sessions() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        BEGIN
          UPDATE platform_auth_sessions
             SET revoked_at = now()
           WHERE platform_user_id = NEW.id
             AND revoked_at IS NULL;
          RETURN NEW;
        END
        $fn$
        """
    )
    op.execute(
        """
        CREATE TRIGGER platform_users_revoke_sessions
          AFTER UPDATE OF password_hash, is_active ON platform_users
          FOR EACH ROW
          WHEN (OLD.password_hash IS DISTINCT FROM NEW.password_hash
                OR (OLD.is_active AND NOT NEW.is_active))
          EXECUTE FUNCTION platform_users_revoke_sessions()
        """
    )

    # --- Journal critique de la plateforme ---
    # `target_company_id`, pas `company_id` : la table n'appartient à aucune entreprise,
    # elle **parle** d'une entreprise. T37 exige la RLS de toute table qui porte
    # `company_id` ; celle-ci n'est lue que par l'administration.
    op.execute(
        """
        CREATE TABLE platform_audit_logs (
          id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          actor_id           uuid REFERENCES platform_users (id),
          action             text NOT NULL
                             CHECK (action IN ('login', 'update', 'insert', 'cancel')),
          entity_table       text NOT NULL CHECK (length(entity_table) BETWEEN 1 AND 63),
          entity_id          uuid,
          target_company_id  uuid REFERENCES companies (id),
          diff               jsonb,
          ip_address         inet,
          occurred_at        timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX platform_audit_logs_company_idx "
        "ON platform_audit_logs (target_company_id, occurred_at DESC)"
    )

    # Les `ALTER DEFAULT PRIVILEGES` des révisions 0001 et 0010 ont donné à `coges_app`
    # et à `coges_analytics` des droits sur chaque table neuve : on les reprend tous.
    # `coges_backup` garde son SELECT (révision 0023) : la sauvegarde est complète.
    for table in PLATFORM_TABLES:
        for role in (APP_ROLE, ANALYTICS_ROLE):
            op.execute(f"REVOKE ALL ON {table} FROM {role}")
    for role in (APP_ROLE, ANALYTICS_ROLE):
        op.execute(f"REVOKE ALL ON SEQUENCE platform_audit_logs_id_seq FROM {role}")

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform_users TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform_auth_sessions TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON platform_audit_logs TO {PLATFORM_ROLE}")

    # --- Lecture des métadonnées à travers la RLS ---
    for table, columns in PLATFORM_READ_COLUMNS.items():
        op.execute(f"GRANT SELECT ({', '.join(columns)}) ON {table} TO {PLATFORM_ROLE}")
        op.execute(
            f"CREATE POLICY {table}_platform_read ON {table} "
            f"FOR SELECT TO {PLATFORM_ROLE} USING (true)"
        )
    # Seule écriture de l'administration chez une entreprise : son statut.
    op.execute(f"GRANT UPDATE (status) ON companies TO {PLATFORM_ROLE}")
    op.execute(
        f"CREATE POLICY companies_platform_status ON companies "
        f"FOR UPDATE TO {PLATFORM_ROLE} USING (true) WITH CHECK (true)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY companies_platform_status ON companies")
    op.execute(f"REVOKE UPDATE (status) ON companies FROM {PLATFORM_ROLE}")
    for table, columns in PLATFORM_READ_COLUMNS.items():
        op.execute(f"DROP POLICY {table}_platform_read ON {table}")
        op.execute(f"REVOKE SELECT ({', '.join(columns)}) ON {table} FROM {PLATFORM_ROLE}")

    op.execute("DROP TABLE platform_audit_logs")
    op.execute("DROP TABLE platform_auth_sessions")
    op.execute("DROP TABLE platform_users")
    op.execute("DROP FUNCTION platform_users_revoke_sessions()")
    op.execute("DROP TYPE platform_role")

    op.execute("DROP TRIGGER companies_status_guard ON companies")
    op.execute("DROP FUNCTION companies_status_guard()")
    op.execute("ALTER TABLE companies DROP COLUMN status")
    op.execute("DROP TYPE company_status")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {PLATFORM_ROLE}")
