"""Redis : aucune clé partagée entre entreprises (lot C, C3 ; ADR 0086).

Inventaire automatique : une série d'opérations pour A et B (tableau de bord en cache,
limitation de débit par IP, par entreprise et par compte, connexion échouée, écriture
qui invalide le cache, battement et tic de beat), puis un SCAN de toutes les clés
créées. Chacune doit être :

* préfixée par `coges:<company_id>:` (cache d'une entreprise) ;
* ou un compteur d'entreprise `coges:rl:tenant:<company_id>:<fenêtre>` ;
* ou un condensat sha256 documenté (`coges:rl:acct:<sha256>`, ADR 0078) ;
* ou une clé globale de la liste blanche commentée ci-dessous.

Une clé inconnue fait échouer le test ; une clé sans expiration aussi.

L'idempotence (corps différent, requêtes simultanées) vit en base et est prouvée par
`tests/integration/test_payments_idempotency.py` ; la même clé envoyée par A et par B,
par `test_list_routes_cross_tenant.py::test_the_idempotency_key_of_a_and_b_never_mix`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
import redis
from fastapi.testclient import TestClient

from app.core import cache, heartbeat, rate_limit
from app.core.config import get_settings
from app.main import app
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    write_headers,
)

pytestmark = pytest.mark.tenancy

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

#: Clés globales permises, et pourquoi elles ne portent aucune entreprise.
GLOBAL_KEYS: dict[str, str] = {
    r"^coges:rl:ip:[^:]+:\d+$": "plafond par adresse IP (ADR 0042), sans entreprise",
    r"^coges:rl:login:[^:]+:\d+$": "plafond de connexion par IP, avant toute entreprise",
    r"^coges:rl:acct:[0-9a-f]{64}(:p|:u)?$": (
        "freinage par compte : sha256(slug|compte ou identifiant), échecs, essais en cours "
        "(:p) et fin d'attente (:u), ADR 0078 et 0088"
    ),
    r"^coges:heartbeat:(worker|beat|relay):[^:]+$": "battement d'un processus (ADR 0077)",
    r"^coges:ops:beat_tick$": "dernier tic de beat (ADR 0077)",
}


@pytest.fixture
def redis_client() -> redis.Redis:
    client = cache.get_client()
    if client is None:
        pytest.skip("Redis requis")
    return client


@pytest.fixture
def limits_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Limitation de débit rallumée, plafonds hors d'atteinte : on veut les clés."""
    high = get_settings().model_copy(
        update={
            "rate_limit_ip_per_minute": 10_000,
            "rate_limit_tenant_per_minute": 10_000,
            "rate_limit_login_per_minute": 10_000,
            "trust_proxy_headers": True,
        }
    )
    monkeypatch.setattr(rate_limit, "get_settings", lambda: high)
    monkeypatch.setattr("app.core.deps.get_settings", lambda: high)
    yield


@pytest.fixture(scope="module")
def pair(app_bound_to_test_database: None) -> tuple[DemoCompany, DemoCompany]:
    marker = uuid4().hex[:6]
    return (
        _create_demo_company(f"redis-a-{marker}"),
        _create_demo_company(f"redis-b-{marker}"),
    )


def _all_keys(client: redis.Redis) -> set[str]:
    return {str(key) for key in client.scan_iter("coges:*", count=1000)}


def _allowed(key: str, companies: set[str]) -> bool:
    match = re.match(rf"^coges:({UUID}):[a-z_]+$", key)
    if match:
        return match.group(1) in companies
    match = re.match(rf"^coges:rl:tenant:({UUID}):\d+$", key)
    if match:
        return match.group(1) in companies
    return any(re.match(pattern, key) for pattern in GLOBAL_KEYS)


def _operations(client: TestClient, a: DemoCompany, b: DemoCompany) -> dict[str, Any]:
    ip = {"x-forwarded-for": f"10.9.{uuid4().int % 250}.{uuid4().int % 250}"}
    tokens = {}
    for company in (a, b):
        tokens[company.slug] = login_token(client, company)
        headers = {**auth_headers(tokens[company.slug]), **ip}
        assert client.get("/api/v1/dashboard", headers=headers).status_code == 200
        assert client.get("/api/v1/customers", headers=headers).status_code == 200
        refused = client.post(
            "/api/v1/auth/login",
            json={"company_slug": company.slug, "email": company.email, "password": "faux-mot"},
            headers=ip,
        )
        assert refused.status_code == 401
    heartbeat.record_beat_tick(heartbeat.redis_client())
    return tokens


def test_every_redis_key_belongs_to_one_company_or_is_declared(
    redis_client: redis.Redis,
    limits_on: None,
    pair: tuple[DemoCompany, DemoCompany],
) -> None:
    a, b = pair
    before = _all_keys(redis_client)
    with TestClient(app, base_url=TEST_BASE_URL) as client:
        _operations(client, a, b)
    created = _all_keys(redis_client) - before

    companies = {str(a.company_id), str(b.company_id)}
    unknown = sorted(key for key in created if not _allowed(key, companies))
    assert unknown == [], f"Clés Redis non classées : {unknown}"
    assert any(str(a.company_id) in key for key in created), "le cache de A doit exister"
    assert any(":rl:acct:" in key for key in created), "le freinage par compte doit exister"
    without_ttl = sorted(key for key in created if redis_client.ttl(key) == -1)
    assert without_ttl == [], f"Clés sans expiration : {without_ttl}"


def test_the_cache_of_a_is_never_served_to_b_nor_cleared_by_a(
    redis_client: redis.Redis, pair: tuple[DemoCompany, DemoCompany]
) -> None:
    a, b = pair
    sentinel_a = {"sentinel": f"A-{uuid4().hex}"}
    sentinel_b = {"sentinel": f"B-{uuid4().hex}"}
    cache.set_json(a.company_id, cache.DASHBOARD_KEY, sentinel_a, ttl_seconds=300)
    cache.set_json(b.company_id, cache.DASHBOARD_KEY, sentinel_b, ttl_seconds=300)

    with TestClient(app, base_url=TEST_BASE_URL) as client:
        token_b = login_token(client, b)
        dashboard_b = client.get("/api/v1/dashboard", headers=auth_headers(token_b))
        assert sentinel_a["sentinel"] not in dashboard_b.text

        # Une écriture de A qui émet un événement invalide le cache de A après COMMIT...
        token_a = login_token(client, a)
        created = client.post(
            "/api/v1/expense-categories",
            headers=write_headers(token_a),
            json={"name": f"Charge {uuid4().hex[:6]}", "kind": "fixed"},
        )
        assert created.status_code == 201, created.text
        expense = client.post(
            "/api/v1/expenses",
            headers=write_headers(token_a),
            json={
                "category_id": created.json()["id"],
                "label": "Invalide le cache de A",
                "amount": "100",
                "spent_at": "2026-10-17",
            },
        )
        assert expense.status_code == 201, expense.text

    assert cache.get_json(a.company_id, cache.DASHBOARD_KEY) != sentinel_a
    # ... et ne touche jamais celui de B.
    assert cache.get_json(b.company_id, cache.DASHBOARD_KEY) == sentinel_b


def test_the_tenant_cap_of_a_does_not_slow_b(
    redis_client: redis.Redis,
    monkeypatch: pytest.MonkeyPatch,
    pair: tuple[DemoCompany, DemoCompany],
) -> None:
    a, b = pair
    low = get_settings().model_copy(update={"rate_limit_tenant_per_minute": 3})
    monkeypatch.setattr(rate_limit, "get_settings", lambda: low)
    monkeypatch.setattr(rate_limit, "_clock", lambda: 1_900_000_000.0 - 1_900_000_000 % 60 + 1)
    for stale in redis_client.scan_iter("coges:rl:tenant:*"):
        redis_client.delete(stale)
    with TestClient(app, base_url=TEST_BASE_URL) as client:
        token_a, token_b = login_token(client, a), login_token(client, b)
        statuses_a = [
            client.get("/api/v1/customers", headers=auth_headers(token_a)).status_code
            for _ in range(5)
        ]
        status_b = client.get("/api/v1/customers", headers=auth_headers(token_b)).status_code
    assert 429 in statuses_a
    assert status_b == 200


def test_the_account_brake_key_does_not_depend_on_whether_the_slug_exists() -> None:
    """Même forme de clé pour une entreprise réelle ou inventée : pas d'énumération."""
    real = rate_limit.account_key("societe-alpha", "gerant@societe-alpha.example.com")
    invented = rate_limit.account_key("n-existe-pas", "gerant@societe-alpha.example.com")
    assert re.match(r"^coges:rl:acct:[0-9a-f]{64}$", real)
    assert re.match(r"^coges:rl:acct:[0-9a-f]{64}$", invented)
    assert real != invented


def test_without_redis_reads_fall_back_to_the_database_for_both(
    monkeypatch: pytest.MonkeyPatch, pair: tuple[DemoCompany, DemoCompany]
) -> None:
    a, b = pair
    monkeypatch.setattr(cache, "get_client", lambda: None)
    with TestClient(app, base_url=TEST_BASE_URL) as client:
        for company in (a, b):
            token = login_token(client, company)
            assert client.get("/api/v1/dashboard", headers=auth_headers(token)).status_code == 200
            category = client.post(
                "/api/v1/categories",
                headers=write_headers(token),
                json={"name": f"Sans Redis {uuid4().hex[:6]}"},
            )
            assert category.status_code == 201, category.text
