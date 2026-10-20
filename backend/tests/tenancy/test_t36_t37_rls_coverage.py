"""T36 et T37 — privilèges du rôle applicatif et couverture RLS.

T37 est **générique** : il interroge le catalogue PostgreSQL, pas une liste écrite à
la main. Toute table d'une phase future qui porterait `company_id` sans RLS ferait
échouer ce test sans que personne ait à le modifier.
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

pytestmark = pytest.mark.tenancy

APP_ROLE = "coges_app"
AUTH_ROLE = "coges_auth"
#: Rôles du chemin asynchrone (phase 08, ADR 0032).
RELAY_ROLE = "coges_relay"
ANALYTICS_ROLE = "coges_analytics"
BUS_ROLE = "coges_bus"
#: Propriétaire des fonctions de surveillance (ADR 0077).
OPS_ROLE = "coges_ops"
BACKUP_ROLE = "coges_backup"

#: Seules tables où le rôle analytique peut supprimer. Elles sont intégralement
#: reconstruisibles depuis le transactionnel : c'est ce qui justifie l'exception.
ANALYTICS_DELETABLE = ["daily_sales_facts"]

#: Tables que le propriétaire des fonctions du bus peut atteindre. Il a BYPASSRLS,
#: donc cette liste **est** la portée réelle du contournement.
BUS_TABLES = ["business_events", "companies", "idempotency_keys"]

#: Seule table que `coges_ops` atteint : le journal des tâches planifiées.
OPS_TABLES = ["job_runs"]

#: Les fonctions du projet dont `EXECUTE` a été retiré à `PUBLIC`. Ce sont celles qui
#: franchissent la RLS ou qui accordent un geste que le rôle appelant n'a pas.
PRIVILEGED_FUNCTIONS = {
    "auth_lookup",
    "ensure_audit_partition",
    "outbox_claim",
    "outbox_mark_published",
    "outbox_release",
    "active_company_ids",
    "purge_expired_idempotency_keys",
    "outbox_lag",
    "job_run_start",
    "job_run_finish",
    "job_runs_latest",
    "purge_job_runs",
}

#: Seules tables sur lesquelles `coges_app` a le droit de supprimer (ADR 0007, 0020).
#: Trois tables du RBAC : aucune n'a de colonne de suppression logique, aucune ne
#: porte de donnée métier historisée, et chaque suppression est auditée.
#: `sale_items` est la quatrième et dernière : retirer une ligne d'un brouillon est
#: un DELETE, et `sale_items_no_change` borne ce droit à la vie du brouillon.
DELETABLE_TABLES = ["role_permissions", "roles", "sale_items", "user_roles"]


def test_t36_application_role_has_no_escape_hatch(app_engine: Engine) -> None:
    """T36 — `coges_app` n'est ni superuser ni BYPASSRLS."""
    with app_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles "
                "WHERE rolname = :role"
            ),
            {"role": APP_ROLE},
        ).one()

    assert row.rolsuper is False, "coges_app est superutilisateur"
    assert row.rolbypassrls is False, "coges_app contourne la RLS"
    assert row.rolcreatedb is False
    assert row.rolcreaterole is False


def test_t36_application_role_connects_as_itself(app_engine: Engine) -> None:
    """T36 — les tests attaquent bien la base en `coges_app`, pas en propriétaire."""
    with app_engine.connect() as connection:
        current = connection.execute(text("SELECT current_user")).scalar_one()
    assert current == APP_ROLE


def test_t36_physical_delete_is_limited_to_three_tables(app_engine: Engine) -> None:
    """T36 — la suppression physique reste l'exception, et elle est nommée.

    Toute table ajoutée par une phase future se retrouverait dans cette liste si
    quelqu'un lui accordait DELETE : le test échouerait sans être modifié.
    """
    with app_engine.connect() as connection:
        granted = (
            connection.execute(
                text(
                    """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND has_table_privilege(:role, c.oid, 'DELETE')
                ORDER BY c.relname
                """
                ),
                {"role": APP_ROLE},
            )
            .scalars()
            .all()
        )

    assert granted == DELETABLE_TABLES, (
        f"DELETE accordé à {APP_ROLE} sur un jeu de tables inattendu : {granted}"
    )


def test_t36_permissions_catalogue_is_read_only(app_engine: Engine) -> None:
    """T36 — `permissions` est un catalogue global : lecture seule pour l'application."""
    with app_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT has_table_privilege(:role, 'permissions', 'SELECT') AS can_read, "
                "has_table_privilege(:role, 'permissions', 'INSERT') AS can_insert, "
                "has_table_privilege(:role, 'permissions', 'UPDATE') AS can_update"
            ),
            {"role": APP_ROLE},
        ).one()

    assert row.can_read is True
    assert row.can_insert is False
    assert row.can_update is False


def test_t37_every_tenant_scoped_table_has_forced_rls(app_engine: Engine) -> None:
    """T37 — toute table portant `company_id` a `relrowsecurity` ET `relforcerowsecurity`.

    Les tables **partitionnées** (`relkind = 'p'`) et chacune de leurs partitions
    sont incluses : une politique posée sur le parent ne protège pas un accès direct
    à une partition (ADR 0008).
    """
    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'p')
                  AND EXISTS (
                        SELECT 1 FROM pg_attribute a
                        WHERE a.attrelid = c.oid
                          AND a.attname = 'company_id'
                          AND a.attnum > 0
                          AND NOT a.attisdropped
                  )
                ORDER BY c.relname
                """
            )
        ).all()

    assert rows, "aucune table tenant-scoped trouvée : le schéma n'est pas migré"
    faulty = [r.relname for r in rows if not (r.relrowsecurity and r.relforcerowsecurity)]
    assert faulty == [], f"RLS absente ou non forcée sur : {faulty}"


def test_t37_every_tenant_scoped_table_has_a_policy(app_engine: Engine) -> None:
    """T37 — chaque table tenant-scoped porte une politique avec USING **et** WITH CHECK."""
    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT c.relname, p.polname, p.polqual IS NOT NULL AS has_using,
                       p.polwithcheck IS NOT NULL AS has_with_check
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_policy p ON p.polrelid = c.oid
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'p')
                  AND EXISTS (
                        SELECT 1 FROM pg_attribute a
                        WHERE a.attrelid = c.oid AND a.attname = 'company_id'
                          AND a.attnum > 0 AND NOT a.attisdropped
                  )
                ORDER BY c.relname
                """
            )
        ).all()

    # Une table est couverte si **une** de ses politiques a USING et WITH CHECK. Les
    # politiques de lecture de l'administration (`*_platform_read`, ADR 0089) n'ont pas
    # de WITH CHECK : elles ne servent qu'au SELECT, et ne nomment que son rôle.
    complete = {r.relname for r in rows if r.polname and r.has_using and r.has_with_check}
    incomplete = sorted({r.relname for r in rows} - complete)
    assert incomplete == [], f"politique absente ou incomplète sur : {incomplete}"


def test_t37_companies_is_protected_against_enumeration(app_engine: Engine) -> None:
    """T37 — `companies` n'a pas de `company_id` : elle est couverte par une politique sur `id`.

    Une seule politique vaut pour tous les rôles ; les autres ne nomment que le rôle de
    l'administration (ADR 0089), qui n'énumère les entreprises que par ses GRANT colonne
    par colonne.
    """
    with app_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity,
                       (SELECT count(*) FROM pg_policy p
                         WHERE p.polrelid = c.oid AND p.polroles = '{0}') AS policies,
                       (SELECT array_agg(p.polname ORDER BY p.polname) FROM pg_policy p
                         WHERE p.polrelid = c.oid AND p.polroles <> '{0}') AS role_policies,
                       (SELECT bool_and(p.polroles = ARRAY['coges_app_platform'::regrole::oid])
                          FROM pg_policy p
                         WHERE p.polrelid = c.oid AND p.polroles <> '{0}') AS platform_only
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'companies'
                """
            )
        ).one()

    assert row.relrowsecurity is True
    assert row.relforcerowsecurity is True
    assert row.policies == 1
    assert row.role_policies == ["companies_platform_read", "companies_platform_status"]
    assert row.platform_only is True


def test_t37_permissions_is_a_global_catalogue(app_engine: Engine) -> None:
    """T37 — `permissions` n'a pas de `company_id` et reste hors RLS, par conception."""
    with app_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT c.relrowsecurity,
                       EXISTS (SELECT 1 FROM pg_attribute a
                               WHERE a.attrelid = c.oid AND a.attname = 'company_id'
                                 AND a.attnum > 0 AND NOT a.attisdropped) AS has_company_id
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'permissions'
                """
            )
        ).one()

    assert row.has_company_id is False
    assert row.relrowsecurity is False


def test_t36_no_login_role_can_bypass_rls(app_engine: Engine) -> None:
    """T36 — `coges_auth` a BYPASSRLS, mais il est NOLOGIN : nul ne s'y connecte.

    Aucun rôle capable de se connecter ne doit pouvoir franchir la RLS (ADR 0005).
    """
    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT rolname, rolcanlogin, rolbypassrls FROM pg_roles "
                "WHERE rolbypassrls AND NOT rolsuper ORDER BY rolname"
            )
        ).all()

    # Seule exception, nommée : la sauvegarde externe (ADR 0084), en lecture seule et
    # jamais sur le VPS ; ses droits sont bornés par les tests qui suivent.
    offenders = [row.rolname for row in rows if row.rolcanlogin and row.rolname != BACKUP_ROLE]
    assert offenders == [], f"Rôles connectables avec BYPASSRLS : {offenders}"
    assert AUTH_ROLE in [row.rolname for row in rows]


def test_t36_backup_role_only_reads(app_engine: Engine) -> None:
    """T36 — `coges_backup` lit tout (pg_dump complet) et n'écrit rien (ADR 0084)."""
    with app_engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolinherit, "
                "rolconfig FROM pg_roles WHERE rolname = :role"
            ),
            {"role": BACKUP_ROLE},
        ).one()
        tables = connection.execute(
            text(
                """
                SELECT c.relname,
                       has_table_privilege(:role, c.oid, 'SELECT') AS can_select,
                       has_table_privilege(:role, c.oid,
                         'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER') AS can_write
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
                ORDER BY c.relname
                """
            ),
            {"role": BACKUP_ROLE},
        ).all()
        memberships = connection.execute(
            text(
                "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member "
                "WHERE r.rolname = :role"
            ),
            {"role": BACKUP_ROLE},
        ).scalar_one()
        can_create = connection.execute(
            text("SELECT has_schema_privilege(:role, 'public', 'CREATE')"),
            {"role": BACKUP_ROLE},
        ).scalar_one()
        definer_functions = (
            connection.execute(
                text(
                    """
                SELECT p.proname FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.prosecdef
                  AND has_function_privilege(:role, p.oid, 'EXECUTE')
                """
                ),
                {"role": BACKUP_ROLE},
            )
            .scalars()
            .all()
        )

    assert not (role.rolsuper or role.rolcreatedb or role.rolcreaterole or role.rolreplication)
    assert role.rolinherit is False
    assert "default_transaction_read_only=on" in (role.rolconfig or [])
    assert tables, "aucune table dans public"
    unreadable = [row.relname for row in tables if not row.can_select]
    writable = [row.relname for row in tables if row.can_write]
    assert unreadable == [], f"Tables que la sauvegarde ne lit pas : {unreadable}"
    assert writable == [], f"Tables que la sauvegarde peut modifier : {writable}"
    assert memberships == 0, "coges_backup ne doit emprunter aucun autre rôle"
    assert can_create is False
    assert definer_functions == [], f"Fonctions privilégiées ouvertes : {definer_functions}"


def test_t36_application_role_is_not_a_member_of_the_auth_role(app_engine: Engine) -> None:
    """T36 — `coges_app` ne doit pas pouvoir emprunter `coges_auth` par SET ROLE."""
    with app_engine.connect() as connection:
        is_member = connection.execute(
            text("SELECT pg_has_role(:app, :auth, 'USAGE')"),
            {"app": APP_ROLE, "auth": AUTH_ROLE},
        ).scalar_one()

    assert is_member is False


def test_t36_audit_log_is_append_only(app_engine: Engine) -> None:
    """T36 — le journal d'audit n'est ni modifiable ni supprimable par l'application."""
    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT c.relname,
                       has_table_privilege(:role, c.oid, 'INSERT') AS can_insert,
                       has_table_privilege(:role, c.oid, 'UPDATE') AS can_update,
                       has_table_privilege(:role, c.oid, 'DELETE') AS can_delete
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'p')
                  AND c.relname LIKE 'audit_logs%'
                ORDER BY c.relname
                """
            ),
            {"role": APP_ROLE},
        ).all()

    assert rows, "audit_logs est absente du schéma"
    for row in rows:
        assert row.can_insert is True, f"{row.relname} : écriture d'audit impossible"
        assert row.can_update is False, f"{row.relname} : une trace d'audit est modifiable"
        assert row.can_delete is False, f"{row.relname} : une trace d'audit est supprimable"


# --------------------------------------------------- phase 08 : chemin asynchrone


def _table_privileges(connection: object, role: str, privilege: str) -> list[str]:
    """Tables `public` sur lesquelles `role` détient `privilege`."""
    return (
        connection.execute(  # type: ignore[attr-defined]
            text(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'p')
                  AND has_table_privilege(:role, c.oid, :privilege)
                ORDER BY c.relname
                """
            ),
            {"role": role, "privilege": privilege},
        )
        .scalars()
        .all()
    )


def test_t36_worker_roles_cannot_bypass_rls(app_engine: Engine) -> None:
    """T36 — les deux rôles des workers sont connectables, donc sans BYPASSRLS.

    Ils posent le même `SET LOCAL` que l'API et vivent sous les mêmes politiques.
    Le seul contournement du projet reste confiné à des fonctions `SECURITY DEFINER`
    appartenant à des rôles NOLOGIN (ADR 0005, 0032).
    """
    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT rolname, rolcanlogin, rolbypassrls, rolsuper FROM pg_roles "
                "WHERE rolname IN (:relay, :analytics) ORDER BY rolname"
            ),
            {"relay": RELAY_ROLE, "analytics": ANALYTICS_ROLE},
        ).all()

    assert [row.rolname for row in rows] == [ANALYTICS_ROLE, RELAY_ROLE], (
        "les rôles des workers ne sont pas créés : voir deploy/postgres/init/01-roles.sql"
    )
    for row in rows:
        assert row.rolcanlogin is True, f"{row.rolname} doit pouvoir se connecter"
        assert row.rolbypassrls is False, f"{row.rolname} contourne la RLS"
        assert row.rolsuper is False, f"{row.rolname} est superutilisateur"


def test_t36_relay_role_holds_no_table_privilege(app_engine: Engine) -> None:
    """T36 — le relais ne touche **aucune** table : il n'exécute que trois fonctions.

    C'est ce qui rend acceptable qu'il voie toutes les entreprises. S'il obtenait un
    jour un `SELECT` direct sur `business_events`, il lirait les données de tous les
    tenants sans passer par la fonction qui borne ce qu'il en voit.
    """
    with app_engine.connect() as connection:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            granted = _table_privileges(connection, RELAY_ROLE, privilege)
            assert granted == [], f"{RELAY_ROLE} détient {privilege} sur : {granted}"


def test_t36_privileged_functions_are_revoked_from_public(app_engine: Engine) -> None:
    """T36 — aucune fonction privilégiée n'est exécutable par `PUBLIC`.

    `EXECUTE` est accordé à `PUBLIC` par défaut sur **toute** fonction. Sans un
    `REVOKE` qui a réellement pris effet, n'importe quel rôle connecté pourrait
    appeler `outbox_claim` et lire l'outbox de toutes les entreprises, ou
    `auth_lookup` et résoudre une identité sans contexte tenant.

    Le piège est qu'un `REVOKE` émis après un transfert de propriété est un **no-op
    silencieux** : PostgreSQL émet un WARNING, pas une erreur. Une entrée d'ACL dont
    le bénéficiaire est vide (`=X/...`) est la signature de cet oubli.
    """
    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT p.proname, p.proacl::text AS acl
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.proname = ANY(:names)
                ORDER BY p.proname
                """
            ),
            {"names": sorted(PRIVILEGED_FUNCTIONS)},
        ).all()

    assert {row.proname for row in rows} == PRIVILEGED_FUNCTIONS, (
        "fonctions privilégiées absentes du schéma : "
        f"{PRIVILEGED_FUNCTIONS - {row.proname for row in rows}}"
    )
    open_to_public = [
        row.proname
        for row in rows
        if row.acl is None or any(entry.startswith("=") for entry in row.acl.strip("{}").split(","))
    ]
    assert open_to_public == [], f"EXECUTE laissé à PUBLIC sur : {open_to_public}"


def test_t36_who_may_call_the_privileged_functions(app_engine: Engine) -> None:
    """T36 — et la liste de qui peut les appeler est exactement celle-ci.

    Le relais réclame l'outbox, personne d'autre. Le rôle applicatif purge les clés
    expirées — ce que son absence de droit DELETE lui interdirait autrement — mais ne
    touche pas à l'outbox. Chaque ligne ci-dessous est une décision, pas un effet de
    bord d'un `GRANT` trop large.
    """
    expected = {
        ("outbox_claim", RELAY_ROLE): True,
        ("outbox_claim", APP_ROLE): False,
        ("outbox_claim", ANALYTICS_ROLE): False,
        ("outbox_mark_published", RELAY_ROLE): True,
        ("outbox_mark_published", APP_ROLE): False,
        # Rend la tentative après une panne de transport (ADR 0087) : le relais seul.
        ("outbox_release", RELAY_ROLE): True,
        ("outbox_release", APP_ROLE): False,
        ("outbox_release", ANALYTICS_ROLE): False,
        ("active_company_ids", RELAY_ROLE): True,
        ("active_company_ids", APP_ROLE): True,
        ("active_company_ids", ANALYTICS_ROLE): True,
        ("purge_expired_idempotency_keys", APP_ROLE): True,
        ("purge_expired_idempotency_keys", RELAY_ROLE): False,
        ("auth_lookup", APP_ROLE): True,
        ("auth_lookup", RELAY_ROLE): False,
        # Surveillance (ADR 0077) : le worker trace, l'API lit le bilan.
        ("outbox_lag", APP_ROLE): True,
        ("outbox_lag", RELAY_ROLE): False,
        ("outbox_lag", ANALYTICS_ROLE): False,
        ("job_run_start", APP_ROLE): True,
        ("job_run_start", RELAY_ROLE): False,
        ("job_run_start", ANALYTICS_ROLE): False,
        ("job_run_finish", APP_ROLE): True,
        ("job_run_finish", ANALYTICS_ROLE): False,
        ("job_runs_latest", APP_ROLE): True,
        ("job_runs_latest", RELAY_ROLE): False,
        ("purge_job_runs", APP_ROLE): True,
        ("purge_job_runs", ANALYTICS_ROLE): False,
    }
    signatures = {
        "outbox_claim": "outbox_claim(integer)",
        "outbox_mark_published": "outbox_mark_published(bigint[])",
        "outbox_release": "outbox_release(bigint[])",
        "active_company_ids": "active_company_ids()",
        "purge_expired_idempotency_keys": "purge_expired_idempotency_keys()",
        "auth_lookup": "auth_lookup(citext, citext)",
        "outbox_lag": "outbox_lag()",
        "job_run_start": "job_run_start(text, uuid)",
        "job_run_finish": "job_run_finish(bigint, text, text)",
        "job_runs_latest": "job_runs_latest(interval)",
        "purge_job_runs": "purge_job_runs()",
    }

    with app_engine.connect() as connection:
        observed = {
            (function, role): connection.execute(
                text("SELECT has_function_privilege(:role, :signature, 'EXECUTE')"),
                {"role": role, "signature": signatures[function]},
            ).scalar_one()
            for function, role in expected
        }

    wrong = {key: value for key, value in observed.items() if value != expected[key]}
    assert wrong == {}, f"droits d'exécution inattendus : {wrong}"


def test_t36_analytics_role_deletes_only_reconstructible_tables(app_engine: Engine) -> None:
    """T36 — le rôle analytique supprime, mais seulement ce qui se reconstruit.

    C'est la cinquième et dernière exception à « pas de suppression physique », et
    elle ne porte sur aucune donnée : `daily_sales_facts` est une projection.
    """
    with app_engine.connect() as connection:
        granted = _table_privileges(connection, ANALYTICS_ROLE, "DELETE")

    assert granted == ANALYTICS_DELETABLE, (
        f"DELETE accordé à {ANALYTICS_ROLE} sur un jeu de tables inattendu : {granted}"
    )


def test_t36_bus_role_reach_is_named(app_engine: Engine) -> None:
    """T36 — `coges_bus` a BYPASSRLS : la liste des tables qu'il atteint est la portée réelle.

    Elle doit rester courte et explicite. Une table qui s'y ajouterait par mégarde —
    par un `GRANT … ON ALL TABLES` distrait — deviendrait lisible pour toutes les
    entreprises à la fois.
    """
    with app_engine.connect() as connection:
        row = connection.execute(
            text("SELECT rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname = :role"),
            {"role": BUS_ROLE},
        ).one()
        reachable = sorted(
            set(_table_privileges(connection, BUS_ROLE, "SELECT"))
            | set(_table_privileges(connection, BUS_ROLE, "INSERT"))
            | set(_table_privileges(connection, BUS_ROLE, "UPDATE"))
            | set(_table_privileges(connection, BUS_ROLE, "DELETE"))
        )

    assert row.rolcanlogin is False, f"{BUS_ROLE} doit rester NOLOGIN"
    assert row.rolbypassrls is True, f"{BUS_ROLE} doit franchir la RLS pour ses fonctions"
    assert reachable == BUS_TABLES, f"portée du contournement inattendue : {reachable}"


def test_t36_ops_role_reach_is_job_runs_only(app_engine: Engine) -> None:
    """T36 — `coges_ops` a BYPASSRLS, NOLOGIN, et n'atteint que `job_runs` (ADR 0077)."""
    with app_engine.connect() as connection:
        row = connection.execute(
            text("SELECT rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname = :role"),
            {"role": OPS_ROLE},
        ).one_or_none()
        assert row is not None, "coges_ops absent : voir deploy/postgres/init/01-roles.sql"
        reachable = sorted(
            set(_table_privileges(connection, OPS_ROLE, "SELECT"))
            | set(_table_privileges(connection, OPS_ROLE, "INSERT"))
            | set(_table_privileges(connection, OPS_ROLE, "UPDATE"))
            | set(_table_privileges(connection, OPS_ROLE, "DELETE"))
        )

    assert row.rolcanlogin is False, f"{OPS_ROLE} doit rester NOLOGIN"
    assert row.rolbypassrls is True
    assert reachable == OPS_TABLES, f"portée du contournement inattendue : {reachable}"


@pytest.mark.parametrize("role", [APP_ROLE, RELAY_ROLE, ANALYTICS_ROLE])
def test_t36_no_runtime_role_touches_job_runs(app_engine: Engine, role: str) -> None:
    """T36 — aucun rôle d'exécution n'a de privilège sur `job_runs` : tout passe par
    les fonctions de `coges_ops`, qui ne rendent jamais un `company_id`."""
    with app_engine.connect() as connection:
        granted = [
            privilege
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
            if "job_runs" in _table_privileges(connection, role, privilege)
        ]
    assert granted == [], f"{role} détient {granted} sur job_runs"


#: Tables du schéma public SANS RLS, chacune avec sa raison (lot C, C2). Toute autre
#: table sans RLS fait échouer la CI : une table de plateforme se déclare ici.
TABLES_WITHOUT_RLS: dict[str, str] = {
    "alembic_version": "révision du schéma, aucune donnée d'entreprise",
    "permissions": "catalogue global des permissions, identique pour toutes (T37)",
    # Administration de la plateforme (ADR 0089) : aucune n'appartient à une entreprise,
    # `coges_app` et `coges_analytics` n'y ont aucun droit (test_platform_role_grants).
    "platform_users": "comptes de l'équipe CoGes, hors de toute entreprise",
    "platform_auth_sessions": "sessions de l'administration, hors de toute entreprise",
    "platform_audit_logs": "journal de l'administration ; parle d'une entreprise, n'en est pas",
}


def test_t37_tables_without_rls_are_named(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        unprotected = set(
            connection.execute(
                text(
                    """
                    SELECT c.relname FROM pg_class c
                    WHERE c.relnamespace = 'public'::regnamespace
                      AND c.relkind IN ('r', 'p') AND NOT c.relispartition
                      AND NOT c.relrowsecurity
                    """
                )
            ).scalars()
        )
    assert unprotected == set(TABLES_WITHOUT_RLS), (
        f"Tables sans RLS non déclarées : {sorted(unprotected - set(TABLES_WITHOUT_RLS))} ; "
        f"déclarées mais protégées ou disparues : {sorted(set(TABLES_WITHOUT_RLS) - unprotected)}"
    )
