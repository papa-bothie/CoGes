"""Le rôle de l'administration ne peut pas lire une donnée commerciale (ADR 0089).

Pas une règle applicative qu'on espère ne pas oublier : une impossibilité au niveau
des GRANT. Le test énumère **toutes** les tables et toutes leurs colonnes, partitions
comprises, et exige que les droits de `coges_app_platform` soient exactement la liste
blanche ci-dessous. Une table ajoutée plus tard sans y penser n'a aucun droit pour lui
— et si quelqu'un lui en donne un, ce test échoue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.modules.platform.repository import AuditReader, MerchantUserDirectory

pytestmark = pytest.mark.tenancy

PLATFORM_ROLE = "coges_app_platform"

#: Tables de la plateforme, ouvertes en entier au rôle.
WHOLE_TABLES: dict[str, set[str]] = {
    "platform_users": {"SELECT", "INSERT", "UPDATE"},
    "platform_auth_sessions": {"SELECT", "INSERT", "UPDATE"},
    "platform_audit_logs": {"SELECT", "INSERT"},
    # Abonnements (ADR 0091) : l'offre se lit, l'abonnement se change, un paiement
    # s'ajoute et ne se corrige pas.
    "plans": {"SELECT"},
    "subscriptions": {"SELECT", "INSERT", "UPDATE"},
    "subscription_payments": {"SELECT", "INSERT"},
}

#: Accès support (ADR 0092) : une session s'ouvre en entier, puis seule sa fermeture
#: s'écrit (`ended_at`, `ended_by`). Aucune autre colonne ne se réécrit.
_SUPPORT_COLUMNS = (
    "id",
    "company_id",
    "platform_user_id",
    "justification",
    "granted_by_user_id",
    "started_at",
    "expires_at",
    "created_at",
)

#: Invitations de l'équipe (ADR 0094) : écrites une fois, puis seul leur cycle de vie
#: change (empreinte du jeton, émission, échéance, acceptation, révocation).
_INVITATION_FIXED = (
    "id",
    "email",
    "display_name",
    "role",
    "idempotency_key",
    "invited_by",
    "created_at",
)
_INVITATION_LIFECYCLE = (
    "token_hash",
    "issue",
    "expires_at",
    "accepted_at",
    "accepted_user_id",
    "revoked_at",
)

#: Double authentification (ADR 0105) : écrites une fois, puis seul leur sort change
#: (jeton intermédiaire consommé, code de secours utilisé ou révoqué, appareil revu).
_MFA_TABLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "platform_mfa_challenges": (
        ("id", "platform_user_id", "token_hash", "purpose", "created_at", "expires_at"),
        ("pending_secret", "consumed_at"),
    ),
    "platform_recovery_codes": (
        ("id", "platform_user_id", "code_hash", "created_at"),
        ("used_at", "revoked_at"),
    ),
    "platform_known_devices": (
        ("id", "platform_user_id", "token_hash", "browser", "first_seen_at"),
        ("last_seen_at",),
    ),
}

#: Tables d'entreprise : quelques colonnes de métadonnées, rien d'autre.
COLUMN_GRANTS: dict[str, dict[str, set[str]]] = {
    **{
        table: {
            **{column: {"SELECT", "INSERT"} for column in fixed},
            **{column: {"SELECT", "INSERT", "UPDATE"} for column in lifecycle},
        }
        for table, (fixed, lifecycle) in _MFA_TABLES.items()
    },
    "platform_invitations": {
        **{column: {"SELECT", "INSERT"} for column in _INVITATION_FIXED},
        **{column: {"SELECT", "INSERT", "UPDATE"} for column in _INVITATION_LIFECYCLE},
    },
    "support_sessions": {
        **{column: {"SELECT", "INSERT"} for column in _SUPPORT_COLUMNS},
        "ended_at": {"SELECT", "INSERT", "UPDATE"},
        "ended_by": {"SELECT", "INSERT", "UPDATE"},
    },
    "companies": {
        "id": {"SELECT"},
        "name": {"SELECT"},
        "slug": {"SELECT"},
        "status": {"SELECT", "UPDATE"},
        "created_at": {"SELECT"},
        "deleted_at": {"SELECT"},
    },
    "users": {
        column: {"SELECT"}
        for column in (
            "id",
            "company_id",
            "full_name",
            "email",
            "phone",
            "is_active",
            "last_login_at",
            "deleted_at",
        )
    },
    "roles": {column: {"SELECT"} for column in ("id", "company_id", "name", "description")},
    "user_roles": {column: {"SELECT"} for column in ("user_id", "role_id", "company_id")},
    # La date seulement : ni `diff`, ni `entity_table`, ni l'acteur.
    "audit_logs": {column: {"SELECT"} for column in ("company_id", "occurred_at")},
}

#: Tables commerciales citées par le prompt : jamais le moindre droit, même en colonne.
COMMERCIAL_TABLES = (
    "sales",
    "sale_items",
    "sale_returns",
    "sale_return_items",
    "sale_return_refunds",
    "inventory_movements",
    "product_stock",
    "products",
    "product_prices",
    "categories",
    "customers",
    "suppliers",
    "payments",
    "payment_allocations",
    "debts",
    "expenses",
    "expense_categories",
    "daily_sales_facts",
    "forecasts",
    "insights",
    "business_events",
)

#: Seules fonctions `SECURITY DEFINER` qu'il exécute (ADR 0090) : des compteurs, des
#: dates, des types d'événement. Jamais `auth_lookup`, jamais les écritures de l'outbox.
MONITORING_FUNCTIONS = {
    "outbox_lag",
    "job_runs_latest",
    "job_runs_history",
    "outbox_dead_letters",
}

#: Privilèges qui existent au niveau de la colonne ; DELETE, TRUNCATE et TRIGGER ne
#: s'accordent qu'à la table entière (vérifiés à part : jamais, nulle part).
_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")


def _column_privileges(connection: Any) -> dict[tuple[str, str], set[str]]:
    rows = connection.execute(
        text(
            """
            SELECT c.relname, a.attname, priv
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            CROSS JOIN unnest(CAST(:privileges AS text[])) AS priv
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
              AND has_column_privilege(:role, c.oid, a.attnum, priv)
            """
        ),
        {"role": PLATFORM_ROLE, "privileges": list(_PRIVILEGES)},
    ).all()
    granted: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        granted.setdefault((row.relname, row.attname), set()).add(row.priv)
    return granted


def test_the_platform_role_has_exactly_its_whitelist(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        granted = _column_privileges(connection)
        columns = connection.execute(
            text(
                "SELECT c.relname, a.attname FROM pg_class c "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 "
                "AND NOT a.attisdropped WHERE c.relname = ANY(:tables)"
            ),
            {"tables": list(WHOLE_TABLES)},
        ).all()

    expected: dict[tuple[str, str], set[str]] = {}
    for row in columns:
        expected[(row.relname, row.attname)] = set(WHOLE_TABLES[row.relname])
    for table, table_columns in COLUMN_GRANTS.items():
        for column, privileges in table_columns.items():
            expected[(table, column)] = set(privileges)

    unexpected = {key: value for key, value in granted.items() if expected.get(key) != value}
    missing = {key: value for key, value in expected.items() if granted.get(key) != value}
    assert unexpected == {}, f"Droits de {PLATFORM_ROLE} hors liste blanche : {unexpected}"
    assert missing == {}, f"Droits attendus absents : {missing}"


def test_the_platform_role_never_deletes_anything(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        tables = (
            connection.execute(
                text(
                    "SELECT c.relname FROM pg_class c "
                    "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p') "
                    "AND has_table_privilege(:role, c.oid, 'DELETE, TRUNCATE, TRIGGER')"
                ),
                {"role": PLATFORM_ROLE},
            )
            .scalars()
            .all()
        )
    assert tables == []


def test_no_commercial_table_is_open_to_the_platform_role(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        tables = {table for table, _ in _column_privileges(connection)}
        present = set(
            connection.execute(
                text("SELECT relname FROM pg_class WHERE relname = ANY(:tables)"),
                {"tables": list(COMMERCIAL_TABLES)},
            ).scalars()
        )
    assert present == set(COMMERCIAL_TABLES), "liste commerciale périmée"
    assert tables & set(COMMERCIAL_TABLES) == set()


def test_the_platform_role_has_no_escape_hatch(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, "
                "rolreplication FROM pg_roles WHERE rolname = :role"
            ),
            {"role": PLATFORM_ROLE},
        ).one()
        memberships = connection.execute(
            text(
                "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member "
                "WHERE r.rolname = :role"
            ),
            {"role": PLATFORM_ROLE},
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
                {"role": PLATFORM_ROLE},
            )
            .scalars()
            .all()
        )
        sequences = (
            connection.execute(
                text(
                    "SELECT c.relname FROM pg_class c WHERE c.relkind = 'S' "
                    "AND c.relnamespace = 'public'::regnamespace "
                    "AND CASE WHEN c.relkind = 'S' "
                    "THEN has_sequence_privilege(:role, c.oid, 'USAGE, SELECT, UPDATE') END"
                ),
                {"role": PLATFORM_ROLE},
            )
            .scalars()
            .all()
        )
    assert role.rolcanlogin is True
    assert not (role.rolsuper or role.rolbypassrls or role.rolcreatedb or role.rolcreaterole)
    assert not role.rolreplication
    assert memberships == 0, "le rôle hérite d'un autre rôle"
    # Une fonction SECURITY DEFINER franchit la RLS pour lui : seules les quatre lectures
    # de surveillance lui sont ouvertes, qui ne rendent ni entreprise ni contenu (ADR 0090).
    assert set(definer_functions) == MONITORING_FUNCTIONS
    assert sequences == []


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT count(*) FROM sales",
        "SELECT count(*) FROM products",
        "SELECT count(*) FROM payments",
        "SELECT diff FROM audit_logs LIMIT 1",
        "SELECT settings FROM companies LIMIT 1",
        "SELECT password_hash FROM users LIMIT 1",
        "UPDATE companies SET name = name",
    ],
)
def test_the_database_itself_refuses_commercial_reads(
    platform_session_factory: sessionmaker[Any], statement: str
) -> None:
    """Sous le vrai rôle, une requête commerciale échoue — pas filtrée : refusée."""
    session = platform_session_factory()
    try:
        with pytest.raises(ProgrammingError, match="permission denied"):
            session.execute(text(statement))
    finally:
        session.rollback()
        session.close()


@pytest.mark.parametrize("sort", ["name", "-name", "last_login", "-last_login"])
def test_merchant_users_and_journal_run_under_the_real_role(
    platform_session_factory: Any, sort: str
) -> None:
    """Lot admin 6 (ADR 0094) : chaque branche des requêtes, sous `coges_app_platform`.
    Une colonne non accordée (téléphone, hachage) ferait échouer en `permission denied`."""
    session = platform_session_factory()
    try:
        for status in (None, "active", "deactivated", "company_suspended"):
            MerchantUserDirectory(session).search(
                search="%a_",
                role="gerant",
                status=status,
                company_id=uuid4(),
                sort=sort,
                page=1,
                page_size=20,
            )
        AuditReader(session).search(
            actor_id=uuid4(),
            action="update",
            company_id=uuid4(),
            entity_id=uuid4(),
            start=datetime(2026, 1, 1, tzinfo=UTC),
            stop=datetime(2026, 12, 31, tzinfo=UTC),
            page=1,
            page_size=50,
        )
    finally:
        session.rollback()
        session.close()
