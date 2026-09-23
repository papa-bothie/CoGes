"""Fixtures partagées par toutes les suites de tests.

Les tests d'intégrité attaquent une **vraie** base : `coges_test` est recréée en
début de session par les migrations Alembic réelles (donc avec leurs triggers et
leurs politiques RLS), puis interrogée avec le rôle **`coges_app`**. La RLS n'est
jamais désactivée.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import create_app_engine
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


@pytest.fixture(scope="session")
def tenant_a(session_factory: sessionmaker[Any], owner_engine: Engine) -> Tenant:
    """Entreprise A du harnais de fuite, partagée par toutes les suites."""
    return create_tenant(session_factory, owner_engine, "entreprise-a")


@pytest.fixture(scope="session")
def tenant_b(session_factory: sessionmaker[Any], owner_engine: Engine) -> Tenant:
    """Entreprise B du harnais de fuite, partagée par toutes les suites."""
    return create_tenant(session_factory, owner_engine, "entreprise-b")
