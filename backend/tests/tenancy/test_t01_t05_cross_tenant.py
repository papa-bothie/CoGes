"""T1 à T5 — isolation inter-tenant prouvée directement sur la base.

Ces tests n'appellent aucun endpoint : ils ouvrent une transaction en `coges_app`,
posent le contexte et interrogent PostgreSQL. Un test qui ne passerait que parce que
l'API a filtré ne vaudrait rien (§ 10 du Modèle de données).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import SET_TENANT_CONTEXT_SQL, tenant_transaction
from tests.tenancy.harness import (
    PLACEHOLDER_PASSWORD_HASH,
    TENANT_TABLES,
    Tenant,
    own_row_ids,
)

pytestmark = pytest.mark.tenancy


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_t01_cross_tenant_read_returns_nothing(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant, table: str
) -> None:
    """T1 — dans le contexte A, aucune ligne de B n'est visible, sur aucune table."""
    foreign = own_row_ids(tenant_b, table)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        # La ligne de B est introuvable...
        visible_b = session.execute(
            text(f"SELECT count(*) FROM {table} WHERE {foreign['clause']}"),
            {"value": foreign["value"]},
        ).scalar_one()
        # ...et aucune ligne visible ne porte un autre company_id.
        leaked = session.execute(
            text(f"SELECT count(*) FROM {table} WHERE company_id <> :company_id"),
            {"company_id": tenant_a.company_id},
        ).scalar_one()
        # A voit bien ses propres données : le test ne passe pas « parce que tout est vide ».
        own = session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()

    assert visible_b == 0, f"fuite de lecture de B vers A sur {table}"
    assert leaked == 0, f"ligne d'un autre tenant visible sur {table}"
    assert own >= 1, f"A ne voit plus ses propres lignes sur {table}"


def test_t01_symmetry_b_cannot_read_a(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """T1 — la symétrie est vérifiée dans les deux sens."""
    with tenant_transaction(tenant_b.ctx, session_factory=session_factory) as session:
        visible_a = session.execute(
            text("SELECT count(*) FROM users WHERE id = :user_id"),
            {"user_id": tenant_a.user_id},
        ).scalar_one()
    assert visible_a == 0


def test_t01_companies_cannot_be_enumerated(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """T1 — `companies` est protégée par une politique sur `id` : pas d'énumération."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        rows = session.execute(text("SELECT id FROM companies")).scalars().all()
    assert rows == [tenant_a.company_id]


def test_t02_cross_tenant_write_is_rejected(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """T2 — dans le contexte A, insérer une ligne portant le company_id de B viole WITH CHECK."""
    with (
        pytest.raises(ProgrammingError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO users (id, company_id, email, password_hash, full_name) "
                "VALUES (:id, :company_id, :email, :password_hash, 'Intrus')"
            ),
            {
                "id": uuid4(),
                "company_id": tenant_b.company_id,
                "email": "intrus@entreprise-b.test",
                "password_hash": PLACEHOLDER_PASSWORD_HASH,
            },
        )

    assert "row-level security" in str(excinfo.value).lower()


def test_t02_cross_tenant_update_is_rejected(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """T2 — déplacer sa propre ligne vers un autre tenant est refusé de la même façon."""
    with (
        pytest.raises(ProgrammingError),
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text("UPDATE users SET company_id = :other WHERE id = :id"),
            {"other": tenant_b.company_id, "id": tenant_a.user_id},
        )


def test_t03_without_context_returns_no_row_and_no_error(
    app_engine: Engine, tenant_a: Tenant
) -> None:
    """T3 — sans contexte : jeu vide, jamais d'erreur, jamais d'accès global.

    C'est le test que la politique du § 8.11 échouerait : après un premier
    `SET LOCAL`, la variable vaut la chaîne vide et `''::uuid` lèverait
    `invalid input syntax for type uuid`. Le `NULLIF` la ramène à NULL (ADR 0003).
    """
    with app_engine.connect() as connection, connection.begin():
        rows = connection.execute(text("SELECT count(*) FROM users")).scalar_one()
        companies = connection.execute(text("SELECT count(*) FROM companies")).scalar_one()

    assert rows == 0
    assert companies == 0


def test_t04_context_does_not_survive_on_a_pooled_connection(
    app_engine: Engine, tenant_a: Tenant
) -> None:
    """T4 — même connexion physique : le contexte de A ne survit pas à sa transaction."""
    with app_engine.connect() as connection:
        # Transaction 1 : contexte A posé avec **le SQL de production**, pas une copie.
        # Si `tenant_transaction` passait un jour en portée session, ce test échouerait.
        with connection.begin():
            connection.execute(SET_TENANT_CONTEXT_SQL, {"company_id": str(tenant_a.company_id)})
            seen_with_context = connection.execute(text("SELECT count(*) FROM users")).scalar_one()

        # Transaction 2 : même connexion, aucun nouveau contexte posé.
        with connection.begin():
            seen_without_context = connection.execute(
                text("SELECT count(*) FROM users")
            ).scalar_one()
            residual = connection.execute(
                text("SELECT current_setting('app.company_id', true)")
            ).scalar_one()

    assert seen_with_context >= 1, "le contexte n'a pas été pris en compte"
    assert seen_without_context == 0, "le contexte a survécu au COMMIT : fuite par le pool"
    # La variable ne revient pas à NULL mais à la chaîne vide : c'est la raison d'être du NULLIF.
    assert residual in (None, "")


def test_t04_reused_pool_connection_sees_only_its_own_tenant(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """T4 — A puis B sur le pool (une seule connexion) : B ne voit jamais les données de A."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        session.execute(text("SELECT count(*) FROM users")).scalar_one()

    with tenant_transaction(tenant_b.ctx, session_factory=session_factory) as session:
        visible_a = session.execute(
            text("SELECT count(*) FROM users WHERE id = :user_id"),
            {"user_id": tenant_a.user_id},
        ).scalar_one()

    assert visible_a == 0


def test_t05_composite_foreign_key_blocks_cross_tenant_link(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """T5 — `user_roles` de A référençant un rôle de B : violation de FK composite."""
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id, company_id) "
                "VALUES (:user_id, :role_id, :company_id)"
            ),
            {
                "user_id": tenant_a.user_id,
                "role_id": tenant_b.role_id,  # rôle de l'autre entreprise
                "company_id": tenant_a.company_id,
            },
        )

    assert isinstance(excinfo.value.orig, Exception)
    assert "foreign key" in str(excinfo.value).lower()


def test_t05_role_permissions_cannot_borrow_a_foreign_role(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """T5 — `role_permissions` de A pointant vers le rôle de B : même refus."""
    with (
        pytest.raises(DBAPIError),
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id, company_id) "
                "VALUES (:role_id, :permission_id, :company_id)"
            ),
            {
                "role_id": tenant_b.role_id,
                "permission_id": tenant_a.permission_id,
                "company_id": tenant_a.company_id,
            },
        )


def test_t04_context_does_not_survive_the_return_to_the_pool(
    session_factory: sessionmaker[Any], app_engine: Engine, tenant_a: Tenant
) -> None:
    """T4 — après une transaction applicative complète, la connexion revient neutre.

    Le pool ne contient qu'une seule connexion : celle que `tenant_transaction` vient
    de rendre est exactement celle que l'on reprend ici.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        assert session.execute(text("SELECT count(*) FROM users")).scalar_one() >= 1

    with app_engine.connect() as connection, connection.begin():
        leaked = connection.execute(text("SELECT count(*) FROM users")).scalar_one()
        residual = connection.execute(
            text("SELECT current_setting('app.company_id', true)")
        ).scalar_one()

    assert leaked == 0, "le contexte a survécu au retour de la connexion dans le pool"
    assert residual in (None, "")
