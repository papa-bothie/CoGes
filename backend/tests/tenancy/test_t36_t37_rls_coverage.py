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


def test_t36_no_physical_delete_anywhere(app_engine: Engine) -> None:
    """T36 — aucun DELETE physique n'est accordé : la suppression est logique."""
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

    assert granted == [], f"DELETE accordé à {APP_ROLE} sur : {granted}"


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
    """T37 — toute table portant `company_id` a `relrowsecurity` ET `relforcerowsecurity`."""
    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
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
                  AND c.relkind = 'r'
                  AND EXISTS (
                        SELECT 1 FROM pg_attribute a
                        WHERE a.attrelid = c.oid AND a.attname = 'company_id'
                          AND a.attnum > 0 AND NOT a.attisdropped
                  )
                ORDER BY c.relname
                """
            )
        ).all()

    incomplete = [
        r.relname for r in rows if r.polname is None or not (r.has_using and r.has_with_check)
    ]
    assert incomplete == [], f"politique absente ou incomplète sur : {incomplete}"


def test_t37_companies_is_protected_against_enumeration(app_engine: Engine) -> None:
    """T37 — `companies` n'a pas de `company_id` : elle est couverte par une politique sur `id`."""
    with app_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity,
                       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'companies'
                """
            )
        ).one()

    assert row.relrowsecurity is True
    assert row.relforcerowsecurity is True
    assert row.policies == 1


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
