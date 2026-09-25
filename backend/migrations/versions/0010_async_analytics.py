"""Chemin asynchrone et couche analytique.

Reprend le § 8.8 (`notifications`) et le § 8.9 (`daily_sales_facts`) du Modèle de
données, et pose ce que la phase 08 exige en plus (ADR 0032, 0033) :

* **`processed_events`** — idempotence des consommateurs. Écrite dans la transaction
  de l'effet : l'effet et sa marque commitent ensemble, donc jamais d'effet sans
  marque ni de marque sans effet.
* **Trois fonctions `SECURITY DEFINER`** appartenant à `coges_bus`
  (NOLOGIN BYPASSRLS). Le relais de l'outbox est le seul composant qui doit voir
  **toutes** les entreprises, or `business_events` est en FORCE ROW LEVEL SECURITY,
  qui s'applique aussi au propriétaire des tables (ADR 0005, mesuré). La surface de
  contournement tient donc en trois fonctions, et `coges_relay` se connecte sans
  aucun privilège de table ni de contournement.
* **Privilèges de `coges_analytics`** (§ 8.11, reporté ici par l'ADR 0004) : seul
  rôle du projet autorisé à `DELETE`, et seulement sur des tables intégralement
  reconstruisibles.

Les rôles eux-mêmes sont créés à l'amorçage du cluster, pas ici : un rôle est un
objet de cluster (ADR 0004). Voir `deploy/postgres/init/01-roles.sql`.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "coges_app"
RELAY_ROLE = "coges_relay"
ANALYTICS_ROLE = "coges_analytics"
BUS_ROLE = "coges_bus"

MANAGER_ROLE = "gerant"
SALESPERSON_ROLE = "vendeur"
ACCOUNTANT_ROLE = "comptable"

#: Tables tenant-scoped créées par cette révision.
TENANT_TABLES = ("daily_sales_facts", "notifications", "processed_events")

#: Tables que le rôle analytique reconstruit, donc les seules où il peut supprimer.
ANALYTIC_TABLES = ("daily_sales_facts",)

#: Nouveaux droits. `read` et `update` existent déjà dans le vocabulaire : le
#: `CHECK` de `permissions.action` n'a pas à bouger.
NEW_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("notifications:read", "notifications", "read"),
    ("notifications:update", "notifications", "update"),
    ("system:read", "system", "read"),
)

#: Qui reçoit quoi, en plus du gérant qui reçoit tout le catalogue. La santé de
#: l'outbox (`system:read`) n'est pas une information de commerce : gérant seul.
PERMISSION_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("notifications:read", (SALESPERSON_ROLE, ACCOUNTANT_ROLE)),
    ("notifications:update", (SALESPERSON_ROLE, ACCOUNTANT_ROLE)),
)


def _rls(table: str) -> None:
    """Politique tenant du projet : forme `NULLIF`, ADR 0003.

    Sans le `NULLIF`, une connexion poolée ayant déjà servi rapporte la chaîne
    vide et non NULL ; `''::uuid` lèverait une erreur là où T3 exige un jeu vide.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE  ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant ON {table}
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )


# --------------------------------------------------------------------- tables


def _daily_sales_facts() -> None:
    """Grain entreprise × jour de vente × produit (§ 4.10).

    Table réelle et non vue matérialisée : une MV échappe aux politiques RLS de ses
    sources, l'exposer à l'API rouvrirait un chemin de lecture sans barrière tenant.
    """
    op.execute(
        """
        CREATE TABLE daily_sales_facts (
           company_id        uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           day               date NOT NULL,
           product_id        uuid NOT NULL,
           category_id       uuid,
           qty_sold          numeric(14,3) NOT NULL DEFAULT 0 CHECK (qty_sold >= 0),
           returned_qty      numeric(14,3) NOT NULL DEFAULT 0 CHECK (returned_qty >= 0),
           net_qty_sold      numeric(14,3) NOT NULL DEFAULT 0,
           gross_revenue     numeric(14,2) NOT NULL DEFAULT 0,
           discount_total    numeric(14,2) NOT NULL DEFAULT 0,
           tax_total         numeric(14,2) NOT NULL DEFAULT 0,
           refund_net_amount numeric(14,2) NOT NULL DEFAULT 0,
           net_revenue       numeric(14,2) NOT NULL DEFAULT 0,
           cogs_gross        numeric(14,2) NOT NULL DEFAULT 0,
           cogs_returned     numeric(14,2) NOT NULL DEFAULT 0,
           cogs_net          numeric(14,2) NOT NULL DEFAULT 0,
           sale_count        integer NOT NULL DEFAULT 0 CHECK (sale_count >= 0),
           built_at          timestamptz NOT NULL DEFAULT now(),
           PRIMARY KEY (company_id, day, product_id),
           CONSTRAINT dsf_product_fk FOREIGN KEY (company_id, product_id)
             REFERENCES products (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT dsf_net_qty_coherent CHECK (net_qty_sold = qty_sold - returned_qty),
           CONSTRAINT dsf_returned_bounds  CHECK (returned_qty <= qty_sold)
        )
        """
    )
    # § 8.10 : company_id toujours en tête, la clause RLS est dans 100 % des requêtes.
    op.execute("CREATE INDEX dsf_day      ON daily_sales_facts (company_id, day)")
    op.execute("CREATE INDEX dsf_product  ON daily_sales_facts (company_id, product_id, day)")
    op.execute("CREATE INDEX dsf_category ON daily_sales_facts (company_id, category_id, day)")
    op.execute("CREATE INDEX dsf_day_brin ON daily_sales_facts USING brin (day)")


def _notifications() -> None:
    """Alertes in-app (§ 8.8).

    Une ligne par destinataire : « lu » est une notion individuelle, et l'index
    partiel `notifs_unread` sert directement le compteur de non-lus (ADR 0032).
    """
    op.execute(
        """
        CREATE TABLE notifications (
           id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           user_id    uuid,
           type       text NOT NULL CHECK (type IN ('stock_low','stock_out','debt_due',
                        'sale_cancelled','forecast_alert','insight_critical')),
           title      text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 160),
           body       text,
           data       jsonb NOT NULL DEFAULT '{}'::jsonb,
           read_at    timestamptz,
           created_at timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT notifications_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT notifications_user_fk FOREIGN KEY (company_id, user_id)
             REFERENCES users (company_id, id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX notifs_unread ON notifications (company_id, user_id) WHERE read_at IS NULL"
    )
    op.execute("CREATE INDEX notifs_recent ON notifications (company_id, created_at DESC)")
    # Déduplication par fenêtre : un même fait ne réveille pas deux fois la même
    # personne. La fenêtre est appliquée par la requête du consommateur ; l'index
    # est ce qui la rend gratuite.
    op.execute(
        "CREATE INDEX notifs_dedupe ON notifications "
        "(company_id, type, user_id, created_at DESC)"
    )


def _processed_events() -> None:
    """Marque d'idempotence des consommateurs (ADR 0032).

    Pas de FK vers `business_events` : l'outbox n'a pas de `UNIQUE (company_id, id)`,
    donc pas de cible composite tenant-aware. La PK et la RLS suffisent — une marque
    orpheline est inoffensive, une marque manquante ne l'est pas.
    """
    op.execute(
        """
        CREATE TABLE processed_events (
           company_id   uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           consumer     text NOT NULL CHECK (length(btrim(consumer)) BETWEEN 1 AND 64),
           event_id     bigint NOT NULL,
           processed_at timestamptz NOT NULL DEFAULT now(),
           PRIMARY KEY (company_id, consumer, event_id)
        )
        """
    )


# ------------------------------------------------------------------ fonctions


def _bus_functions() -> None:
    """Les trois fonctions que le relais et le scheduler sont seuls à appeler."""
    # Réclame un lot : verrouille sans attendre les lignes déjà prises par un autre
    # relais (SKIP LOCKED), consomme une tentative, rend l'événement complet. Le
    # filtre `attempts < 10` est ce qui borne le rebut : `business_events` porte un
    # CHECK `attempts <= 10`, donc une onzième tentative lèverait 23514.
    op.execute(
        """
        CREATE FUNCTION outbox_claim(p_batch integer)
        RETURNS TABLE (id bigint, company_id uuid, event_type text,
                       aggregate_type text, aggregate_id uuid, payload jsonb,
                       occurred_at timestamptz, attempts smallint)
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           UPDATE public.business_events e
              SET attempts = e.attempts + 1
            WHERE e.id IN (
                  SELECT c.id
                    FROM public.business_events c
                   WHERE c.published_at IS NULL
                     AND c.attempts < 10
                   ORDER BY c.id
                   FOR UPDATE SKIP LOCKED
                   LIMIT p_batch)
        RETURNING e.id, e.company_id, e.event_type, e.aggregate_type,
                  e.aggregate_id, e.payload, e.occurred_at, e.attempts
        $fn$
        """
    )
    # Marque publiés les seuls événements réellement partis dans Redis. Un crash
    # entre `outbox_claim` et cet appel laisse `published_at` NULL : l'événement est
    # réclamé de nouveau au redémarrage. C'est exactement le test T40.
    op.execute(
        """
        CREATE FUNCTION outbox_mark_published(p_ids bigint[])
        RETURNS integer
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           WITH marked AS (
              UPDATE public.business_events
                 SET published_at = now()
               WHERE id = ANY(p_ids)
                 AND published_at IS NULL
              RETURNING 1)
           SELECT count(*)::integer FROM marked
        $fn$
        """
    )
    # Purge des clés d'idempotence expirées, dette laissée par l'ADR 0027.
    #
    # `coges_app` n'a le droit DELETE nulle part, et c'est un invariant du projet
    # (T36). Plutôt que de lui ouvrir une cinquième exception, le ménage passe par une
    # fonction — exactement le procédé d'`ensure_audit_partition` (ADR 0008), qui
    # donne au rôle applicatif un geste précis qu'il ne pourrait pas faire autrement.
    #
    # Propriétaire `coges_bus` et non `coges_owner` : `FORCE ROW LEVEL SECURITY`
    # s'applique aussi au propriétaire des tables, donc un DELETE sans contexte
    # tenant ne supprimerait **rien, en silence**. La fonction est volontairement
    # inter-entreprises : une clé expirée n'appartient plus à personne.
    op.execute(
        """
        CREATE FUNCTION purge_expired_idempotency_keys()
        RETURNS integer
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           WITH purged AS (
              DELETE FROM public.idempotency_keys
               WHERE expires_at < now()
              RETURNING 1)
           SELECT count(*)::integer FROM purged
        $fn$
        """
    )

    # Ne rend que des identifiants : aucune donnée métier ne franchit la barrière.
    # Le scheduler boucle ensuite entreprise par entreprise, sous RLS normale.
    op.execute(
        """
        CREATE FUNCTION active_company_ids()
        RETURNS TABLE (company_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           SELECT c.id FROM public.companies c
            WHERE c.deleted_at IS NULL
            ORDER BY c.id
        $fn$
        """
    )

    # BYPASSRLS franchit les **politiques**, pas les GRANT : sans ces deux droits,
    # les fonctions échouent en « permission denied for table business_events »
    # une fois leur propriété transférée. Même nécessité que le
    # `GRANT SELECT ON companies, users TO coges_auth` de la révision 0002.
    op.execute(f"GRANT SELECT, UPDATE ON business_events TO {BUS_ROLE}")
    op.execute(f"GRANT SELECT ON companies TO {BUS_ROLE}")
    op.execute(f"GRANT SELECT, DELETE ON idempotency_keys TO {BUS_ROLE}")

    # ---- Droits d'exécution, **avant** le transfert de propriété ----
    #
    # L'ordre n'est pas cosmétique. Une fois la fonction transférée, `coges_owner`
    # n'en est plus le propriétaire : ses REVOKE et ses GRANT deviennent des
    # **no-op silencieux** (PostgreSQL émet un WARNING, pas une erreur), et la
    # fonction reste exécutable par `PUBLIC` — donc par n'importe quel rôle connecté.
    # Constaté sur la révision 0002 : `auth_lookup` portait encore `=X/coges_auth`,
    # c'est-à-dire un `EXECUTE` ouvert à tous, contre la lettre de l'ADR 0005.
    # Réparé ci-dessous.
    grants: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("outbox_claim(integer)", (RELAY_ROLE,)),
        ("outbox_mark_published(bigint[])", (RELAY_ROLE,)),
        ("active_company_ids()", (RELAY_ROLE, ANALYTICS_ROLE, APP_ROLE)),
        ("purge_expired_idempotency_keys()", (APP_ROLE,)),
    )
    for signature, roles in grants:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        for role in roles:
            op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}")

    # Le transfert de propriété exige CREATE sur le schéma : accordé le temps du
    # transfert, puis retiré — `coges_bus` ne doit pouvoir créer aucun objet. Les
    # droits explicites posés ci-dessus survivent au changement de propriétaire
    # (vérifié) : seule l'entrée du propriétaire est réécrite.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {BUS_ROLE}")
    for signature, _ in grants:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {BUS_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {BUS_ROLE}")

    _repair_auth_lookup_acl()


def _repair_auth_lookup_acl() -> None:
    """Referme `auth_lookup` sur `coges_app`, comme l'ADR 0005 l'exigeait.

    La révision 0002 a révoqué `PUBLIC` **après** avoir transféré la propriété à
    `coges_auth` : le REVOKE et le GRANT n'ont rien fait, et la fonction qui franchit
    la RLS pour retrouver une identité est restée exécutable par tout rôle connecté.
    La révision 0002 n'est pas réécrite — une migration livrée ne se modifie pas — donc
    la correction est posée ici, en avant.

    Emprunter `coges_auth` est nécessaire : seul le propriétaire peut modifier l'ACL,
    et `coges_owner` n'est membre de `coges_auth` qu'avec `INHERIT FALSE`, c'est-à-dire
    sans en hériter les droits sans le dire. L'emprunt est `SET LOCAL` comme tout le
    reste du projet : Alembic exécute la révision dans une transaction, le rôle retombe
    donc au COMMIT — et surtout au ROLLBACK, si une instruction suivante échoue.
    """
    op.execute("SET LOCAL ROLE coges_auth")
    op.execute("REVOKE ALL ON FUNCTION auth_lookup(citext, citext) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_lookup(citext, citext) TO {APP_ROLE}")
    op.execute("RESET ROLE")


# ------------------------------------------------------------------ privilèges


def _worker_privileges() -> None:
    """`coges_relay` ne touche aucune table ; `coges_analytics` écrit ses projections."""
    analytic = ", ".join(ANALYTIC_TABLES)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {RELAY_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ANALYTICS_ROLE}")

    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ANALYTICS_ROLE}")
    op.execute(f"GRANT INSERT, UPDATE, DELETE ON {analytic} TO {ANALYTICS_ROLE}")
    # Sa marque d'idempotence commite avec son effet : il doit pouvoir l'écrire.
    op.execute(f"GRANT INSERT ON processed_events TO {ANALYTICS_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION rebuild_product_stock(uuid) TO {ANALYTICS_ROLE}")
    # Tables analytiques des phases suivantes (forecasts, insights) : même régime,
    # automatiquement. Les privilèges d'écriture restent nommés, table par table.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {ANALYTICS_ROLE}"
    )


def _drop_worker_privileges() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM {ANALYTICS_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ANALYTICS_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION rebuild_product_stock(uuid) FROM {ANALYTICS_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ANALYTICS_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {RELAY_ROLE}")


# ---------------------------------------------------------------- permissions


def _add_permissions() -> None:
    rows = ", ".join(
        f"('{code}', '{resource}', '{action}')" for code, resource, action in NEW_PERMISSIONS
    )
    op.execute(f"INSERT INTO permissions (code, resource, action) VALUES {rows}")

    # `roles` et `role_permissions` sont en FORCE ROW LEVEL SECURITY : sans ce
    # NO FORCE, l'INSERT … SELECT du propriétaire n'insérerait rien, **en silence**
    # (ADR 0008, 0024). Même procédé que la révision 0009.
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE roles            NO FORCE ROW LEVEL SECURITY")

    # Le gérant reçoit tout le catalogue ; les deux autres, la liste ci-dessus.
    for code, _, _ in NEW_PERMISSIONS:
        _grant_to_roles(code, (MANAGER_ROLE,))
    for code, roles in PERMISSION_GRANTS:
        _grant_to_roles(code, roles)

    op.execute("ALTER TABLE roles            FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")


def _grant_to_roles(code: str, roles: tuple[str, ...]) -> None:
    names = ", ".join(f"'{role}'" for role in roles)
    op.execute(
        f"""
        INSERT INTO role_permissions (company_id, role_id, permission_id)
        SELECT r.company_id, r.id, p.id
          FROM roles r
          CROSS JOIN permissions p
         WHERE r.name IN ({names})
           AND r.is_system
           AND p.code = '{code}'
        ON CONFLICT DO NOTHING
        """
    )


def _drop_permissions() -> None:
    codes = ", ".join(f"'{code}'" for code, _, _ in NEW_PERMISSIONS)
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"DELETE FROM role_permissions "
        f"WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ({codes}))"
    )
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes})")


# --------------------------------------------------------------------- upgrade


def upgrade() -> None:
    _daily_sales_facts()
    _notifications()
    _processed_events()
    for table in TENANT_TABLES:
        _rls(table)

    _bus_functions()
    _worker_privileges()
    _add_permissions()


def downgrade() -> None:
    _drop_permissions()
    _drop_worker_privileges()

    # L'ACL d'`auth_lookup` est rendue telle que la révision 0002 la laisse, pour que
    # `downgrade` puis `upgrade` retombe exactement sur le même état.
    op.execute("SET LOCAL ROLE coges_auth")
    op.execute("GRANT EXECUTE ON FUNCTION auth_lookup(citext, citext) TO PUBLIC")
    op.execute(f"REVOKE ALL ON FUNCTION auth_lookup(citext, citext) FROM {APP_ROLE}")
    op.execute("RESET ROLE")

    op.execute("DROP FUNCTION IF EXISTS purge_expired_idempotency_keys()")
    op.execute("DROP FUNCTION IF EXISTS active_company_ids()")
    op.execute("DROP FUNCTION IF EXISTS outbox_mark_published(bigint[])")
    op.execute("DROP FUNCTION IF EXISTS outbox_claim(integer)")
    op.execute(f"REVOKE ALL ON business_events, companies, idempotency_keys FROM {BUS_ROLE}")

    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table}")
