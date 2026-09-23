"""Socle plateforme : tenant, RBAC, RLS.

Bande A du Diagramme 3 : companies, users, roles, permissions, user_roles,
role_permissions. Le SQL reproduit les § 8.1, 8.2, 8.10 et 8.11 du Modèle de
données V1.1, noms de contraintes compris.

Trois écarts assumés, tous consignés en ADR :

* ADR 0003 — les politiques RLS utilisent `NULLIF(current_setting(...), '')::uuid`.
  Après un premier `SET LOCAL`, PostgreSQL ne ramène pas un paramètre personnalisé
  à NULL mais à la chaîne vide, et `''::uuid` lève une erreur. Sans le `NULLIF`,
  l'absence de contexte produirait une exception au lieu d'un jeu vide (test T3).
* ADR 0004 — la migration ne crée pas le rôle `coges_app` (objet de cluster, non de
  base) : elle ne pose que les privilèges, plus les privilèges par défaut qui
  couvriront les tables des phases suivantes.
* ADR 0004 — `permissions` est un catalogue global : `coges_app` n'y a que SELECT.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables tenant-scoped créées par cette révision (§ 8.11).
TENANT_TABLES = ("users", "roles", "user_roles", "role_permissions")

# Tables portant `updated_at` : le trigger est nommé `<table>_set_updated_at`.
# Le § 8.1 définit la fonction mais n'attache aucun trigger ; le nom est donc une
# convention de ce projet, à reprendre dans les phases suivantes.
TABLES_WITH_UPDATED_AT = ("companies", "users", "roles")

APP_ROLE = "coges_app"


def upgrade() -> None:
    # ------------------------------------------------------------------ 8.1
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")  # emails, slugs
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")  # EXCLUDE sur intervalles
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # recherche par nom

    op.execute("CREATE TYPE sale_status AS ENUM ('draft','confirmed','cancelled')")
    op.execute(
        "CREATE TYPE movement_type AS ENUM ('initial','purchase_in','sale_out',"
        "'customer_return_in','supplier_return_out','adjustment','loss')"
    )
    op.execute("CREATE TYPE expense_kind AS ENUM ('fixed','variable')")
    op.execute("CREATE TYPE party_type AS ENUM ('customer','supplier')")
    op.execute("CREATE TYPE debt_status AS ENUM ('open','partially_paid','paid','written_off')")
    op.execute("CREATE TYPE cash_direction AS ENUM ('inflow','outflow')")
    op.execute(
        "CREATE TYPE pay_method AS ENUM ('cash','mobile_money','bank_transfer','card','cheque')"
    )
    op.execute(
        "CREATE TYPE return_refund_status AS ENUM ('none_due','pending','partial','settled')"
    )
    op.execute(
        "CREATE TYPE forecast_type AS ENUM ('demand_qty','revenue','stockout_date','cash_balance')"
    )
    op.execute(
        "CREATE TYPE insight_type AS ENUM ('stockout_risk','slow_mover','demand_spike',"
        "'margin_drop','expense_anomaly','cash_shortfall','debt_overdue','cashier_anomaly')"
    )
    op.execute("CREATE TYPE insight_severity AS ENUM ('info','warning','critical')")
    op.execute(
        "CREATE TYPE insight_status AS ENUM ('new','read','acknowledged','dismissed','resolved')"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN NEW.updated_at := now(); RETURN NEW; END $$ LANGUAGE plpgsql
        """
    )

    # Formule CMP unique, partagée par le trigger et la reconstruction :
    # aucune divergence possible entre temps réel et recalcul.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cmp_next_avg(
           p_qty numeric, p_avg numeric, p_delta numeric, p_cost numeric)
        RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
           SELECT CASE
              WHEN p_delta <= 0        THEN p_avg                    -- sortie : inchangé
              WHEN p_qty + p_delta = 0 THEN p_avg                    -- garde-fou 0/0
              ELSE round((p_qty * p_avg + p_delta * p_cost) / (p_qty + p_delta), 4)
           END;
        $$
        """
    )

    # ------------------------------------------------------------------ 8.2
    op.execute(
        """
        CREATE TABLE companies (
           id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           name         text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
           slug         citext NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{3,40}$'),
           currency     char(3) NOT NULL DEFAULT 'XOF' CHECK (currency ~ '^[A-Z]{3}$'),
           timezone     text NOT NULL DEFAULT 'UTC',
           settings     jsonb NOT NULL DEFAULT '{}'::jsonb,
           created_at   timestamptz NOT NULL DEFAULT now(),
           updated_at   timestamptz NOT NULL DEFAULT now(),
           deleted_at   timestamptz
        )
        """
    )

    # La regex d'e-mail est coupée par l'extraction PDF du § 8.2 ; elle est
    # reconstituée ici sur une seule ligne, sans autre changement.
    op.execute(
        r"""
        CREATE TABLE users (
           id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           email         citext NOT NULL
                         CHECK (email ~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'),
           password_hash text NOT NULL,
           full_name     text NOT NULL CHECK (length(btrim(full_name)) > 0),
           is_active     boolean NOT NULL DEFAULT true,
           last_login_at timestamptz,
           created_at    timestamptz NOT NULL DEFAULT now(),
           updated_at    timestamptz NOT NULL DEFAULT now(),
           deleted_at    timestamptz,
           CONSTRAINT users_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT users_email_uq  UNIQUE (company_id, email)   -- unicité PAR tenant
        )
        """
    )

    op.execute(
        """
        CREATE TABLE roles (
           id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id  uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           name        text NOT NULL CHECK (length(btrim(name)) > 0),
           description text,
           is_system   boolean NOT NULL DEFAULT false,
           created_at  timestamptz NOT NULL DEFAULT now(),
           updated_at  timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT roles_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT roles_name_uq   UNIQUE (company_id, name)
        )
        """
    )

    # Catalogue GLOBAL : vocabulaire des droits commun à tous les tenants.
    op.execute(
        """
        CREATE TABLE permissions (
           id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           code     text NOT NULL UNIQUE,
           resource text NOT NULL,
           action   text NOT NULL CHECK (action IN ('read','create','update','delete',
                                                    'confirm','cancel','export'))
        )
        """
    )

    op.execute(
        """
        CREATE TABLE user_roles (
           user_id    uuid NOT NULL,
           role_id    uuid NOT NULL,
           company_id uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           granted_at timestamptz NOT NULL DEFAULT now(),
           PRIMARY KEY (user_id, role_id),
           FOREIGN KEY (company_id, user_id) REFERENCES users (company_id, id)
             ON DELETE CASCADE,
           FOREIGN KEY (company_id, role_id) REFERENCES roles (company_id, id)
             ON DELETE RESTRICT
        )
        """
    )

    op.execute(
        """
        CREATE TABLE role_permissions (
           role_id       uuid NOT NULL,
           permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE RESTRICT,
           company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           PRIMARY KEY (role_id, permission_id),
           FOREIGN KEY (company_id, role_id) REFERENCES roles (company_id, id)
             ON DELETE CASCADE
        )
        """
    )

    # ----------------------------------------------------------------- 8.10
    op.execute(
        "CREATE UNIQUE INDEX companies_live_uq ON companies (id) WHERE deleted_at IS NULL"
    )
    op.execute("CREATE INDEX users_live      ON users (company_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX user_roles_user ON user_roles (company_id, user_id)")
    op.execute("CREATE INDEX role_perms_role ON role_permissions (company_id, role_id)")

    # -------------------------------------------------------- triggers updated_at
    for table in TABLES_WITH_UPDATED_AT:
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    # ----------------------------------------------------------------- 8.11
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE  ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
              USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
              WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
            """
        )

    # companies : politique sur id, pour empêcher l'énumération des tenants.
    op.execute("ALTER TABLE companies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE companies FORCE  ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY companies_self ON companies
          USING      (id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )
    # permissions : catalogue global, aucune donnée d'entreprise, pas de RLS.

    # ------------------------------------------- privilèges du rôle applicatif
    # Le rôle lui-même est créé à l'amorçage du cluster, pas ici (ADR 0004).
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    # Catalogue global en lecture seule : un tenant ne s'invente pas un droit.
    op.execute(f"REVOKE INSERT, UPDATE ON permissions FROM {APP_ROLE}")
    op.execute(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")

    # Tables et séquences des phases suivantes : mêmes privilèges, automatiquement.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE ON TABLES FROM {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE ON SEQUENCES FROM {APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")

    op.execute("DROP POLICY IF EXISTS companies_self ON companies")
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")

    for table in TABLES_WITH_UPDATED_AT:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_set_updated_at ON {table}")

    op.execute("DROP TABLE IF EXISTS role_permissions")
    op.execute("DROP TABLE IF EXISTS user_roles")
    op.execute("DROP TABLE IF EXISTS permissions")
    op.execute("DROP TABLE IF EXISTS roles")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS companies")

    op.execute("DROP FUNCTION IF EXISTS cmp_next_avg(numeric, numeric, numeric, numeric)")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")

    for enum_type in (
        "insight_status",
        "insight_severity",
        "insight_type",
        "forecast_type",
        "return_refund_status",
        "pay_method",
        "cash_direction",
        "debt_status",
        "party_type",
        "expense_kind",
        "movement_type",
        "sale_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")

    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
    op.execute("DROP EXTENSION IF EXISTS citext")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
