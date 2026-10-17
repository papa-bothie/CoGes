"""Échec au COMMIT sur TOUTES les écritures critiques (lot C, C1 ; ADR 0086).

Le lot A (ADR 0079) l'a prouvé sur trois écritures, par un trigger différé posé sur
l'outbox. Ici, le même mécanisme, réel, est généralisé : un trigger de contrainte
`DEFERRABLE INITIALLY DEFERRED` est posé sur **chaque** table qui porte des données
d'une entreprise (et sur `companies`). Toute transaction qui a écrit pour l'entreprise
de test échoue donc au moment exact du COMMIT, après que le service a tout écrit et que
le routeur a construit sa réponse.

Pour chaque route classée « critique » dans `commit_failure_registry.py` :

1. réponse 5xx, jamais 2xx ;
2. **empreinte** de toutes les données de l'entreprise identique avant et après (aucune
   ligne écrite, aucun événement d'outbox, aucune entrée d'audit, aucune clé
   d'idempotence enregistrée) ;
3. cache Redis du tableau de bord ni invalidé à tort ni remplacé ;
4. trigger retiré, le **même** appel (même clé) réussit ;
5. pour une écriture à clé d'idempotence, un troisième envoi identique (la réponse
   précédente s'est « perdue ») rend la même réponse sans rien réécrire.

Toute route d'écriture absente du registre fait échouer `test_every_write_is_classified`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core import cache
from app.core.idempotency import IDEMPOTENCY_HEADER
from app.core.tenancy import TenantContext, tenant_transaction
from app.main import app
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
)
from tests.helpers.invariants import assert_consistent
from tests.integration.commit_failure_registry import (
    KEYED,
    REGISTRY,
    Call,
    Critical,
    Exempt,
    World,
    write_routes,
)

pytestmark = pytest.mark.integration

_FAIL_FUNCTION = """
CREATE OR REPLACE FUNCTION test_c1_fail_at_commit() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE
    target uuid := TG_ARGV[0]::uuid;
    owner uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        owner := CASE WHEN TG_TABLE_NAME = 'companies' THEN OLD.id ELSE OLD.company_id END;
    ELSE
        owner := CASE WHEN TG_TABLE_NAME = 'companies' THEN NEW.id ELSE NEW.company_id END;
    END IF;
    IF owner = target THEN
        RAISE EXCEPTION 'échec de COMMIT provoqué par le test (C1)';
    END IF;
    RETURN NULL;
END
$fn$
"""

_TENANT_TABLES = text(
    """
    SELECT c.relname FROM pg_class c
    JOIN pg_attribute a
      ON a.attrelid = c.oid AND a.attname = 'company_id' AND NOT a.attisdropped
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
      AND NOT c.relispartition
    ORDER BY c.relname
    """
)


def _tables(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return [*connection.execute(_TENANT_TABLES).scalars(), "companies"]


@contextmanager
def failing_commit(owner_engine: Engine, company_id: UUID) -> Iterator[None]:
    tables = _tables(owner_engine)
    with owner_engine.begin() as connection:
        connection.execute(text(_FAIL_FUNCTION))
        for table in tables:
            connection.execute(
                text(
                    f"CREATE CONSTRAINT TRIGGER test_c1_fail_at_commit "
                    f"AFTER INSERT OR UPDATE OR DELETE ON {table} "
                    f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                    f"EXECUTE FUNCTION test_c1_fail_at_commit('{company_id}')"
                )
            )
    try:
        yield
    finally:
        with owner_engine.begin() as connection:
            for table in tables:
                connection.execute(text(f"DROP TRIGGER test_c1_fail_at_commit ON {table}"))
            connection.execute(text("DROP FUNCTION test_c1_fail_at_commit()"))


def snapshot(
    engine: Engine, session_factory: sessionmaker[Any], company_id: UUID
) -> dict[str, str]:
    """Empreinte de toutes les données de l'entreprise, table par table (à travers la RLS)."""
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        # Ce que l'application peut lire : `job_runs` (ADR 0077) n'est écrite que par les
        # fonctions de `coges_ops`, jamais par une requête HTTP.
        tables = [
            table
            for table in _tables(engine)
            if session.execute(
                text("SELECT has_table_privilege(current_user, :t, 'SELECT')"), {"t": table}
            ).scalar_one()
        ]
        return {
            table: session.execute(
                text(
                    f"SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) "
                    f"FROM {table} x" + (" WHERE x.id = :c" if table == "companies" else "")
                ),
                {"c": company_id},
            ).scalar_one()
            for table in tables
        }


def _changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(table for table in before if before[table] != after.get(table))


@pytest.fixture(scope="module")
def commit_company(app_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"commit-c1-{uuid4().hex[:6]}")


@pytest.fixture
def raw_client(app_bound_to_test_database: None) -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL, raise_server_exceptions=False) as client:
        yield client


def _send(client: TestClient, token: str, call: Call, key: str) -> Any:
    headers = {**auth_headers(token), IDEMPOTENCY_HEADER: key}
    return client.request(
        call.method,
        call.path,
        headers=headers,
        json=call.json if call.files is None else None,
        files=call.files,
        params=call.params,
    )


def test_every_write_is_classified() -> None:
    routes = write_routes(app.openapi())
    missing = sorted(routes - REGISTRY.keys())
    stale = sorted(REGISTRY.keys() - routes)
    assert missing == [], f"Écritures à classer dans commit_failure_registry.py : {missing}"
    assert stale == [], f"Entrées du registre sans route : {stale}"
    for route, entry in REGISTRY.items():
        if isinstance(entry, Exempt):
            assert len(entry.reason) > 20, f"{route} : raison d'exemption trop courte"


CRITICAL = sorted(route for route, entry in REGISTRY.items() if isinstance(entry, Critical))


@pytest.mark.parametrize(("method", "path"), CRITICAL, ids=[f"{m} {p}" for m, p in CRITICAL])
def test_a_refused_commit_is_never_reported_as_done(
    method: str,
    path: str,
    raw_client: TestClient,
    commit_company: DemoCompany,
    owner_engine: Engine,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> None:
    token = login_token(raw_client, commit_company)
    world = World(raw_client, token, commit_company, session_factory, analytics_session_factory)
    entry = REGISTRY[(method, path)]
    assert isinstance(entry, Critical)
    call = entry.scenario(world)
    assert call.method == method
    key = uuid4().hex
    company_id = commit_company.company_id

    redis_client = cache.get_client()
    sentinel = {"sentinel": uuid4().hex}
    if redis_client is not None:
        cache.set_json(company_id, cache.DASHBOARD_KEY, sentinel, ttl_seconds=300)

    before = snapshot(owner_engine, session_factory, company_id)
    with failing_commit(owner_engine, company_id):
        failed = _send(raw_client, token, call, key)
    after = snapshot(owner_engine, session_factory, company_id)

    assert failed.status_code >= 500, f"{method} {path} → {failed.status_code} {failed.text}"
    assert _changed(before, after) == [], "le COMMIT refusé a laissé des écritures"
    if redis_client is not None:
        assert cache.get_json(company_id, cache.DASHBOARD_KEY) == sentinel, (
            "cache du tableau de bord touché par une écriture qui n'a pas eu lieu"
        )

    replayed = _send(raw_client, token, call, key)
    assert replayed.status_code < 300, f"rejeu : {replayed.status_code} {replayed.text}"
    written = snapshot(owner_engine, session_factory, company_id)
    assert _changed(before, written) != [], "le rejeu n'a rien écrit"

    assert_consistent(owner_engine, company_id)

    if path in KEYED:
        # La réponse du rejeu s'est « perdue » : le client renvoie la même demande.
        again = _send(raw_client, token, call, key)
        assert again.status_code == replayed.status_code
        assert again.json() == replayed.json()
        assert _changed(written, snapshot(owner_engine, session_factory, company_id)) == [], (
            "un rejeu à l'identique a écrit une seconde fois"
        )
