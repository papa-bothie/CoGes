"""Fixtures partagées par toutes les suites de tests.

Les tests d'intégrité attaquent une **vraie** base : `coges_test` est recréée en
début de session par les migrations Alembic réelles (donc avec leurs triggers et
leurs politiques RLS), puis interrogée avec le rôle **`coges_app`**. La RLS n'est
jamais désactivée.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import redis
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
from app.core.idempotency import IDEMPOTENCY_HEADER
from app.core.tenancy import TenantContext, tenant_transaction
from app.main import app
from tests.tenancy.harness import Tenant, create_tenant

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: Les clients de test parlent en HTTPS, comme le navigateur en préproduction et en
#: production. Hors `local`, le cookie de rafraîchissement est `Secure` (ADR 0006) :
#: un client en `http://` le recevrait sans jamais le renvoyer, et `/auth/refresh`
#: répondrait 401 en CI alors qu'il fonctionne en vrai.
TEST_BASE_URL = "https://testserver"


@pytest.fixture(autouse=True)
def _no_task_broker(monkeypatch: MonkeyPatch) -> None:
    """Aucun test ne dépose de tâche dans le Redis de développement.

    Une demande d'export enfile une tâche worker (ADR 0041) : sans cette barrière,
    un worker local la ramasserait ensuite, avec l'identifiant d'une base de test.
    Les tests qui veulent voir l'enfilement installent leur propre substitut.
    """
    from app.core import queue
    from app.modules.importexport import service as importexport_service

    monkeypatch.setattr(queue, "enqueue", lambda *args, **kwargs: True)
    # Sans worker, chaque export demandé reste en attente : le plafond par entreprise
    # (ADR 0088) bloquerait les suites qui en demandent plusieurs. Son test le remet.
    monkeypatch.setattr(importexport_service, "MAX_PENDING_EXPORTS", 10_000)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Client HTTP sur l'application FastAPI, sans base de données."""
    with TestClient(app, base_url=TEST_BASE_URL) as test_client:
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
def worker_urls() -> tuple[str, str]:
    """DSN des deux rôles de workers : (relais, analytique).

    Les tests de la phase 08 ne peuvent pas se contenter de `coges_app` : la purge des
    faits exige DELETE, que le rôle applicatif n'a nulle part, et la lecture de
    l'outbox exige les fonctions réservées au relais. Utiliser `coges_app` ferait
    passer les tests pour de mauvaises raisons — ou les ferait échouer alors que le
    code de production, lui, fonctionne.
    """
    settings = get_settings()
    relay_url = settings.test_database_url_relay
    analytics_url = settings.test_database_url_analytics
    if not relay_url or not analytics_url:
        pytest.skip(
            "COGES_TEST_DATABASE_URL_RELAY et COGES_TEST_DATABASE_URL_ANALYTICS sont "
            "requis pour les tests du chemin asynchrone."
        )
    return relay_url, analytics_url


@pytest.fixture(scope="session")
def analytics_session_factory(
    migrated_database: str, worker_urls: tuple[str, str]
) -> Iterator[sessionmaker[Any]]:
    """Sessions en `coges_analytics` : SELECT partout, écriture sur les projections."""
    _, analytics_url = worker_urls
    engine: Engine = create_app_engine(analytics_url, pool_size=2, max_overflow=0)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def relay_session_factory(
    migrated_database: str, worker_urls: tuple[str, str]
) -> Iterator[sessionmaker[Any]]:
    """Sessions en `coges_relay` : aucune table, trois fonctions."""
    relay_url, _ = worker_urls
    engine: Engine = create_app_engine(relay_url, pool_size=2, max_overflow=0)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()


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


@pytest.fixture
def concurrent_session_factory(
    migrated_database: str, database_urls: tuple[str, str]
) -> Iterator[sessionmaker[Any]]:
    """Fabrique de sessions sur un pool de **trois** connexions.

    Le pool de la suite n'en contient qu'une — c'est ce qu'exige T4, qui prouve
    qu'une connexion rendue au pool ne garde aucun contexte. Les tests de
    concurrence en demandent trois : une pour le rendez-vous tenu par le test, deux
    pour les acteurs qui se disputent la même ressource.
    """
    _, app_url = database_urls
    engine: Engine = create_app_engine(app_url, pool_size=3, max_overflow=0)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()


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
def workers_bound_to_test_database(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> Iterator[None]:
    """Fait pointer les **tâches** sur `coges_test`, comme `api_client` le fait pour l'API.

    Une tâche n'a pas de client HTTP pour la brancher : elle ouvre sa session
    elle-même, par la fabrique de son rôle. Trois points d'entrée sont donc
    redirigés — le gestionnaire transactionnel commun (déjà fait par
    `app_bound_to_test_database`), la fabrique analytique, et l'énumération des
    entreprises des batchs.

    Sans cette fixture, une tâche appelée depuis un test écrirait dans la base de
    **développement** : elle n'y trouverait pas le tenant du test, et la clé étrangère
    vers `companies` le dirait — tardivement, et de façon déroutante.
    """
    patcher = MonkeyPatch()
    patcher.setattr(
        "app.workers.tasks.analytics.get_analytics_session_factory",
        lambda: analytics_session_factory,
    )
    patcher.setattr("app.workers.tenants.get_session_factory", lambda: session_factory)
    try:
        yield
    finally:
        patcher.undo()


class _IdempotentClient(TestClient):
    """Client de test qui pose une clé d'idempotence neuve sur chaque requête.

    Depuis la phase 07, plusieurs écritures exigent `Idempotency-Key` (ADR 0027).
    Le poser ici plutôt que dans chaque test reproduit ce que fait une vraie
    bibliothèque cliente, et évite qu'un test d'autre chose n'échoue sur un
    en-tête manquant.

    Une clé **explicite** n'est jamais écrasée : c'est ainsi qu'un test rejoue une
    requête à l'identique. Et parce que la clé est neuve par défaut, deux appels
    successifs restent deux demandes distinctes — la confirmation d'une vente doit
    pouvoir se heurter à `sale_not_draft` (ADR 0022), pas à un rejeu.
    """

    def request(self, *args: Any, **kwargs: Any) -> Any:
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault(IDEMPOTENCY_HEADER, uuid4().hex)
        kwargs["headers"] = headers
        return super().request(*args, **kwargs)


@pytest.fixture
def api_client(app_bound_to_test_database: None) -> Iterator[TestClient]:
    """Client HTTP branché sur la base de test."""
    with _IdempotentClient(app, base_url=TEST_BASE_URL) as test_client:
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


def role_id(client: TestClient, token: str, name: str) -> str:
    """Identifiant d'un rôle système de l'entreprise du jeton."""
    response = client.get("/api/v1/roles?page_size=50", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return next(role["id"] for role in response.json()["items"] if role["name"] == name)


def create_user_with_role(
    client: TestClient,
    token: str,
    company: DemoCompany,
    *,
    role: str,
    email: str,
) -> str:
    """Crée un compte porteur d'un rôle système et renvoie son jeton d'accès.

    Passe par les routes réelles : `users:create` du gérant, puis une connexion.
    Aucun raccourci d'insertion — un compte fabriqué à la main n'aurait ni sel
    Argon2, ni rôle attribué par le service qui vérifie l'appartenance au tenant.
    """
    created = client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={
            "email": email,
            "full_name": f"Compte {role}",
            "password": TEST_PASSWORD,
            "role_ids": [role_id(client, token, role)],
        },
    )
    assert created.status_code == 201, created.text

    login = client.post(
        "/api/v1/auth/login",
        json={"company_slug": company.slug, "email": email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    access_token: str = login.json()["access_token"]
    return access_token


def write_headers(token: str, key: str | None = None) -> dict[str, str]:
    """Jeton **et** clé d'idempotence, neuve par défaut.

    Depuis la phase 07, toute écriture financière exige `Idempotency-Key`
    (ADR 0027). Passer `key` explicitement permet de rejouer la même requête ; sans
    argument, chaque appel est une demande neuve.
    """
    return {**auth_headers(token), IDEMPOTENCY_HEADER: key or uuid4().hex}


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


#: Base Redis réservée aux tests de surveillance (ADR 0077) : vidée avant et après,
#: elle ne touche ni le cache ni la file d'un `make dev` qui tournerait à côté (base 0),
#: ni les parcours e2e (base 1).
OPS_REDIS_DB = 15


@pytest.fixture
def ops_redis(monkeypatch: pytest.MonkeyPatch) -> Iterator[redis.Redis]:
    """Client Redis sur la base 15, branché à la place de `heartbeat.redis_client`."""
    base = get_settings().redis_url
    url = re.sub(r"/\d+$", "", base) + f"/{OPS_REDIS_DB}"
    client = redis.Redis.from_url(
        url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
    )
    try:
        client.ping()
    except redis.RedisError:
        pytest.skip("Redis requis")
    client.flushdb()
    monkeypatch.setattr("app.core.heartbeat.redis_client", lambda: client)
    try:
        yield client
    finally:
        client.flushdb()
