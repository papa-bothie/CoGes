"""Authentification, sessions, audit partitionné et outbox transactionnelle.

Reprend le § 8.8 du Modèle de données (`audit_logs`, `business_events`) et comble
les deux trous identifiés dans `docs/architecture/README.md` :

* **P2** — `auth_lookup(slug, email)` : la connexion doit lire `companies` et `users`
  avant d'avoir un contexte tenant. La fonction appartient à `coges_auth`
  (NOLOGIN BYPASSRLS), seul moyen de franchir un `FORCE ROW LEVEL SECURITY` qui
  s'applique aussi au propriétaire des tables. Elle renvoie quatre colonnes, pour un
  seul couple (slug, e-mail). Voir ADR 0005.
* **P3** — `auth_sessions` : refresh rotatif avec détection de réutilisation.

Durcissements décidés en phase 02 (ADR 0008) :

* `CHECK` sur `business_events.event_type` : la liste des 9 événements est fermée ;
* `REVOKE UPDATE ON audit_logs` : le journal est append-only ;
* chaque partition d'`audit_logs` reçoit sa propre RLS forcée — une politique posée
  sur le parent ne couvre pas un accès direct à la partition ;
* partition `DEFAULT` : une partition mensuelle manquante ferait échouer tout INSERT,
  donc toute vente à auditer. Le filet évite qu'une panne de batch devienne une
  panne de caisse.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "coges_app"
AUTH_ROLE = "coges_auth"

# Liste fermée, identique à `app.core.events.types.EventType`. Un test vérifie
# qu'aucune des deux ne dérive de l'autre.
EVENT_TYPES = (
    "sale.confirmed",
    "sale.cancelled",
    "sale.returned",
    "sale_return.refunded",
    "stock.updated",
    "payment.received",
    "debt.created",
    "debt.settled",
    "expense.created",
)

# Catalogue global des droits : `ressource:action`. Le rattachement aux rôles est
# fait par entreprise à la création de celle-ci (app/cli.py), pas ici.
PERMISSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("company", ("read", "update")),
    ("users", ("read", "create", "update", "delete")),
    ("roles", ("read", "create", "update", "delete")),
    ("audit", ("read", "export")),
    ("categories", ("read", "create", "update", "delete")),
    ("products", ("read", "create", "update", "delete")),
    ("prices", ("read", "create")),
    ("customers", ("read", "create", "update", "delete")),
    ("suppliers", ("read", "create", "update", "delete")),
    ("sales", ("read", "create", "update", "confirm", "cancel", "export")),
    ("sale_returns", ("read", "create", "confirm")),
    ("inventory", ("read", "create", "update")),
    ("payments", ("read", "create", "update", "cancel")),
    ("expenses", ("read", "create", "update", "delete")),
    ("debts", ("read", "create", "update")),
    ("dashboard", ("read",)),
    ("analytics", ("read", "export")),
    ("insights", ("read", "update")),
    ("importexport", ("create", "export")),
)

TENANT_TABLES = ("auth_sessions", "business_events")


def _rls(table: str) -> None:
    """Applique le gabarit de politique du projet (ADR 0003) à une table."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE  ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant ON {table}
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )


def upgrade() -> None:
    # ------------------------------------------------------ sessions (point P3)
    op.execute(
        """
        CREATE TABLE auth_sessions (
           id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id  uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           user_id     uuid NOT NULL,
           token_hash  text NOT NULL UNIQUE,
           family_id   uuid NOT NULL,
           issued_at   timestamptz NOT NULL DEFAULT now(),
           expires_at  timestamptz NOT NULL,
           revoked_at  timestamptz,
           replaced_by uuid,
           user_agent  text,
           ip_address  inet,
           CONSTRAINT auth_sessions_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT auth_sessions_user_fk FOREIGN KEY (company_id, user_id)
             REFERENCES users (company_id, id) ON DELETE CASCADE,
           CONSTRAINT auth_sessions_replaced_fk FOREIGN KEY (company_id, replaced_by)
             REFERENCES auth_sessions (company_id, id),
           CONSTRAINT auth_sessions_expiry_chk CHECK (expires_at > issued_at)
        )
        """
    )
    op.execute("CREATE INDEX auth_sessions_family ON auth_sessions (company_id, family_id)")
    op.execute(
        "CREATE INDEX auth_sessions_live ON auth_sessions (company_id, user_id, expires_at DESC) "
        "WHERE revoked_at IS NULL"
    )

    # ----------------------------------------------------------- audit_logs (§ 8.8)
    op.execute(
        """
        CREATE TABLE audit_logs (
           id            bigint GENERATED ALWAYS AS IDENTITY,
           company_id    uuid NOT NULL,
           actor_user_id uuid,
           action        text NOT NULL CHECK (action IN ('insert','update','delete',
                           'login','export','confirm','cancel','rebuild')),
           entity_table  text NOT NULL,
           entity_id     uuid,
           diff          jsonb,
           ip_address    inet,
           occurred_at   timestamptz NOT NULL DEFAULT now(),
           PRIMARY KEY (id, occurred_at)
        ) PARTITION BY RANGE (occurred_at)
        """
    )
    _rls("audit_logs")
    op.execute("CREATE INDEX audit_logs_entity ON audit_logs (company_id, entity_table, entity_id)")
    op.execute("CREATE INDEX audit_logs_actor  ON audit_logs (company_id, occurred_at DESC)")

    # Création d'une partition mensuelle, avec sa RLS et ses privilèges.
    # SECURITY DEFINER : la tâche planifiée de la phase 08 tourne en coges_app, qui
    # n'a aucun droit DDL.
    op.execute(
        """
        CREATE FUNCTION ensure_audit_partition(p_month date)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
        DECLARE
           v_start date := date_trunc('month', p_month)::date;
           v_end   date := (date_trunc('month', p_month) + interval '1 month')::date;
           v_name  text := 'audit_logs_' || to_char(v_start, 'YYYY') || 'm'
                           || to_char(v_start, 'MM');
        BEGIN
           IF to_regclass('public.' || v_name) IS NOT NULL THEN
              RETURN v_name;
           END IF;

           -- Noms qualifiés : avec `search_path = pg_catalog, public`, un nom nu
           -- serait créé dans pg_catalog, où coges_owner n'a aucun droit.
           EXECUTE format(
              'CREATE TABLE public.%I PARTITION OF public.audit_logs '
              'FOR VALUES FROM (%L) TO (%L)',
              v_name, v_start, v_end);

           -- Une politique posée sur le parent ne s'applique pas à un accès direct
           -- à la partition : chaque partition porte donc la sienne (ADR 0008).
           EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', v_name);
           EXECUTE format('ALTER TABLE public.%I FORCE  ROW LEVEL SECURITY', v_name);
           EXECUTE format($pol$
              CREATE POLICY %1$I_tenant ON public.%1$I
                USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
                WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
           $pol$, v_name);

           -- Journal append-only : ni UPDATE ni DELETE, jamais.
           EXECUTE format('GRANT SELECT, INSERT ON public.%I TO coges_app', v_name);
           EXECUTE format('REVOKE UPDATE, DELETE ON public.%I FROM coges_app', v_name);

           RETURN v_name;
        END $fn$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION ensure_audit_partition(date) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION ensure_audit_partition(date) TO {APP_ROLE}")

    # Filet de sécurité : aucune écriture d'audit ne peut échouer faute de partition.
    op.execute("CREATE TABLE audit_logs_default PARTITION OF audit_logs DEFAULT")
    op.execute("ALTER TABLE audit_logs_default ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs_default FORCE  ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_logs_default_tenant ON audit_logs_default
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )

    # Mois courant et mois suivant.
    op.execute("SELECT ensure_audit_partition(current_date)")
    op.execute("SELECT ensure_audit_partition((current_date + interval '1 month')::date)")

    op.execute(f"REVOKE UPDATE, DELETE ON audit_logs FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON audit_logs_default FROM {APP_ROLE}")

    # ------------------------------------------- business_events — outbox (§ 8.8)
    event_list = ", ".join(f"'{event}'" for event in EVENT_TYPES)
    op.execute(
        f"""
        CREATE TABLE business_events (
           id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
           company_id     uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           event_type     text NOT NULL CHECK (event_type IN ({event_list})),
           aggregate_type text NOT NULL,
           aggregate_id   uuid NOT NULL,
           payload        jsonb NOT NULL,
           occurred_at    timestamptz NOT NULL DEFAULT now(),
           published_at   timestamptz,
           attempts       smallint NOT NULL DEFAULT 0 CHECK (attempts <= 10)
        )
        """
    )
    op.execute(
        "CREATE INDEX business_events_unpublished ON business_events (company_id, occurred_at) "
        "WHERE published_at IS NULL"
    )

    for table in TENANT_TABLES:
        _rls(table)

    # ------------------------------------------- auth_lookup — point P2 (ADR 0005)
    op.execute(
        """
        CREATE FUNCTION auth_lookup(p_slug citext, p_email citext)
        RETURNS TABLE (company_id uuid, user_id uuid, password_hash text, is_active boolean)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           SELECT c.id, u.id, u.password_hash, u.is_active
           FROM public.companies c
           JOIN public.users u ON u.company_id = c.id
           WHERE c.slug = p_slug
             AND u.email = p_email
             AND c.deleted_at IS NULL
             AND u.deleted_at IS NULL
        $fn$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT ON companies, users TO {AUTH_ROLE}")
    # Transférer la propriété exige que le futur propriétaire ait CREATE sur le
    # schéma. On le lui accorde le temps du transfert, puis on le retire : coges_auth
    # ne doit pouvoir créer aucun objet.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(f"ALTER FUNCTION auth_lookup(citext, citext) OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")
    op.execute("REVOKE ALL ON FUNCTION auth_lookup(citext, citext) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_lookup(citext, citext) TO {APP_ROLE}")

    # ------------------------------------------------- catalogue des permissions
    # ----------------------------------------------------- DELETE ciblé (ADR 0007)
    # Trois exceptions à « pas de DELETE », et trois seulement : deux tables de
    # liaison et `roles`. Ce ne sont pas des données métier historisées, et aucune
    # n'a de colonne de suppression logique. La FK `user_roles -> roles` est en
    # ON DELETE RESTRICT : un rôle encore porté ne peut pas disparaître. Chaque
    # suppression passe par un audit critique.
    op.execute(f"GRANT DELETE ON user_roles, role_permissions, roles TO {APP_ROLE}")

    rows = ", ".join(
        f"('{resource}:{action}', '{resource}', '{action}')"
        for resource, actions in PERMISSIONS
        for action in actions
    )
    op.execute(f"INSERT INTO permissions (code, resource, action) VALUES {rows}")


def downgrade() -> None:
    # Le catalogue `permissions` est livré par cette révision ; les rattachements
    # `role_permissions` (table de la révision 0001) le référencent. Ils doivent
    # donc partir d'abord, sinon la FK bloque.
    #
    # Attention : `FORCE ROW LEVEL SECURITY` s'applique **aussi** au propriétaire,
    # donc à la migration. Un `DELETE` sans contexte tenant ne supprimerait
    # silencieusement aucune ligne. On lève `FORCE` le temps du nettoyage, puis on
    # le rétablit immédiatement.
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM role_permissions")
    op.execute("ALTER TABLE role_permissions FORCE  ROW LEVEL SECURITY")
    op.execute("DELETE FROM permissions")
    op.execute(f"REVOKE DELETE ON user_roles, role_permissions, roles FROM {APP_ROLE}")

    op.execute("DROP FUNCTION IF EXISTS auth_lookup(citext, citext)")
    op.execute(f"REVOKE ALL ON companies, users FROM {AUTH_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {AUTH_ROLE}")

    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
    op.execute("DROP TABLE IF EXISTS business_events")

    op.execute("DROP TABLE IF EXISTS audit_logs")  # emporte ses partitions
    op.execute("DROP FUNCTION IF EXISTS ensure_audit_partition(date)")

    op.execute("DROP TABLE IF EXISTS auth_sessions")
