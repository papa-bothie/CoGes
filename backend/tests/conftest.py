"""Fixtures partagées par toutes les suites de tests.

Les tests d'intégrité attaquent une **vraie** base : `coges_test` est recréée en
début de session par les migrations Alembic réelles (donc avec leurs triggers et
leurs politiques RLS), puis interrogée avec le rôle **`coges_app`**. La RLS n'est
jamais désactivée.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from _pytest.monkeypatch import MonkeyPatch
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.cli import create_company
from app.core.config import get_settings
from app.core.database import create_app_engine
from app.core.tenancy import TenantContext, tenant_transaction
from app.main import app
from tests.tenancy.harness import Tenant, create_tenant

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Client HTTP sur l'application FastAPI, sans base de données."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def database_urls() -> tuple[str, str]:
    """DSN de la base de test : (propriétaire, applicatif)."""
    settings = get_settings()
    owner_url = settings.test_database_url_owner
    app_url = settings.test_database_url_app
    if not owner_url or not app_url:
        pytest.skip(
            "COGES_TEST_DATABASE_URL_OWNER et COGES_TEST_DATABASE_URL_APP sont requis "
            "pour les tests qui touchent la base."
        )
    return owner_url, app_url


@pytest.fixture(scope="session")
def migrated_database(database_urls: tuple[str, str]) -> str:
    """Recrée `coges_test` à partir de zéro avec les vraies migrations."""
    owner_url, _ = database_urls
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    # Imposé ici : env.py ne l'écrase pas, la base de développement reste intacte.
    config.set_main_option("sqlalchemy.url", owner_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return owner_url


@pytest.fixture(scope="session")
def owner_engine(migrated_database: str) -> Iterator[Engine]:
    """Engine du rôle propriétaire.

    Réservé à ce que l'application ne fait jamais : alimenter le catalogue global
    `permissions`, qui est peuplé par une migration et non par un tenant.
    """
    engine = create_engine(migrated_database, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def app_engine(migrated_database: str, database_urls: tuple[str, str]) -> Iterator[Engine]:
    """Engine connecté en `coges_app` : ni superuser, ni BYPASSRLS, pas de DELETE."""
    _, app_url = database_urls
    # Pool d'une seule connexion : le test T4 exige de réutiliser la même connexion
    # physique d'une transaction à l'autre.
    engine = create_app_engine(app_url, pool_size=1, max_overflow=0)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def session_factory(app_engine: Engine) -> sessionmaker[Any]:
    """Fabrique de sessions sur la base de test, en `coges_app`."""
    return sessionmaker(bind=app_engine, expire_on_commit=False, future=True)


#: Mot de passe des comptes de test. Valeur factice, sans usage hors de la suite.
TEST_PASSWORD = "mot-de-passe-de-test-01"  # noqa: S105


@pytest.fixture(scope="session")
def tenant_a(session_factory: sessionmaker[Any], owner_engine: Engine) -> Tenant:
    """Entreprise A du harnais de fuite, partagée par toutes les suites."""
    return create_tenant(session_factory, owner_engine, "entreprise-a", password=TEST_PASSWORD)


@pytest.fixture(scope="session")
def tenant_b(session_factory: sessionmaker[Any], owner_engine: Engine) -> Tenant:
    """Entreprise B du harnais de fuite, partagée par toutes les suites."""
    return create_tenant(session_factory, owner_engine, "entreprise-b", password=TEST_PASSWORD)


@pytest.fixture(scope="session")
def app_bound_to_test_database(session_factory: sessionmaker[Any]) -> Iterator[None]:
    """Fait pointer l'application sur `coges_test` au lieu de la base de développement.

    Seuls les deux points d'entrée qui ouvrent une session sont redirigés : le
    gestionnaire transactionnel unique et la transaction de recherche d'identité.
    """
    patcher = MonkeyPatch()
    patcher.setattr("app.core.tenancy.get_session_factory", lambda: session_factory)
    patcher.setattr("app.modules.auth.repository.get_session_factory", lambda: session_factory)
    try:
        yield
    finally:
        patcher.undo()


@pytest.fixture
def api_client(app_bound_to_test_database: None) -> Iterator[TestClient]:
    """Client HTTP branché sur la base de test."""
    with TestClient(app) as test_client:
        yield test_client


@dataclass(frozen=True, slots=True)
class DemoCompany:
    """Entreprise complète : rôles système et gérant, créée comme en production."""

    company_id: UUID
    manager_id: UUID
    slug: str
    email: str


def _create_demo_company(slug: str) -> DemoCompany:
    """Passe par la **vraie** commande d'onboarding, pas par un raccourci de test."""
    email = f"gerant@{slug}.example.com"
    company_id, manager_id = create_company(
        name=slug.replace("-", " ").title(),
        slug=slug,
        manager_email=email,
        manager_name="Gérante de test",
        password=TEST_PASSWORD,
        currency="XOF",
        timezone="Africa/Dakar",
    )
    return DemoCompany(
        company_id=UUID(company_id), manager_id=UUID(manager_id), slug=slug, email=email
    )


@pytest.fixture(scope="session")
def company_alpha(app_bound_to_test_database: None) -> DemoCompany:
    """Entreprise de référence des tests d'API."""
    return _create_demo_company("societe-alpha")


@pytest.fixture(scope="session")
def company_beta(app_bound_to_test_database: None) -> DemoCompany:
    """Seconde entreprise : sert aux appels croisés, qui doivent donner 404."""
    return _create_demo_company("societe-beta")


def login_token(client: TestClient, company: DemoCompany, *, password: str = TEST_PASSWORD) -> str:
    """Jeton d'accès d'un gérant."""
    response = client.post(
        "/api/v1/auth/login",
        json={"company_slug": company.slug, "email": company.email, "password": password},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


@pytest.fixture
def alpha_token(api_client: TestClient, company_alpha: DemoCompany) -> str:
    """Jeton du gérant d'alpha, qui possède toutes les permissions."""
    return login_token(api_client, company_alpha)


@pytest.fixture
def beta_token(api_client: TestClient, company_beta: DemoCompany) -> str:
    """Jeton du gérant de beta."""
    return login_token(api_client, company_beta)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def read_scalar_in_tenant(
    session_factory: sessionmaker[Any],
    company_id: UUID,
    sql: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """Lit une valeur **à travers la RLS**, avec le contexte du tenant.

    Le rôle propriétaire ne peut pas servir à vérifier une donnée tenant-scoped :
    `FORCE ROW LEVEL SECURITY` s'applique aussi à lui, il ne verrait rien.
    """
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        return session.execute(text(sql), params or {}).scalar_one()
