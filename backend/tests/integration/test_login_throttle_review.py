"""Freinage de la connexion, quatre trous de la revue (P2.4, ADR 0088).

(a) un seul mauvais essai toutes les 30 min maintenait la victime bloquée, même avec le
    bon mot de passe : les échecs comptent désormais 45 min (fenêtre + attente maximale),
    puis s'effacent ;
(b) vérifier → Argon2 → compter n'était pas atomique : une rafale parallèle passait en
    entier avant le premier échec compté ;
(c) un compte joignable par e-mail et par téléphone avait deux compteurs ;
(d) sans Redis, un flot d'identifiants fantaisistes évinçait le compteur de la victime,
    et un échec gardé en mémoire était oublié quand Redis revenait.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import cache, rate_limit
from app.core.config import get_settings
from app.main import app
from app.modules.auth import service as auth_service
from tests.conftest import (
    TEST_BASE_URL,
    TEST_PASSWORD,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
)

pytestmark = pytest.mark.integration

START = 1_800_000_000.0
WRONG = "mauvais-mot"


class _Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(rate_limit, "_clock", fake)
    return fake


def _small_memory(monkeypatch: pytest.MonkeyPatch, capacity: int) -> None:
    monkeypatch.setattr(rate_limit, "_memory", rate_limit._MemoryCounters(capacity))
    if hasattr(rate_limit, "_MemoryAccounts"):
        monkeypatch.setattr(rate_limit, "_memory_accounts", rate_limit._MemoryAccounts(capacity))


@pytest.fixture
def throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(
        update={
            "login_throttle_free_failures": 5,
            "login_throttle_window_minutes": 15,
            "login_throttle_max_wait_minutes": 30,
            "login_throttle_alert_after": 10,
            "rate_limit_login_per_minute": 0,
            "rate_limit_ip_per_minute": 0,
        }
    )
    monkeypatch.setattr(rate_limit, "get_settings", lambda: settings)
    monkeypatch.setattr(auth_service, "get_settings", lambda: settings)
    _small_memory(monkeypatch, 10_000)


@pytest.fixture
def redis_required() -> None:
    if cache.get_client() is None:
        pytest.skip("Redis requis")


@pytest.fixture
def company(app_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"frein-{uuid4().hex[:8]}")


def _login(client: TestClient, slug: str, identifier: str, password: str) -> Any:
    return client.post(
        "/api/v1/auth/login",
        json={"company_slug": slug, "identifier": identifier, "password": password},
    )


@pytest.mark.usefixtures("redis_required", "throttle")
def test_a_failure_every_30_minutes_no_longer_keeps_the_owner_out(
    client: TestClient, company: DemoCompany, clock: _Clock
) -> None:
    """(a) L'attaquant échoue une fois toutes les 30 min ; la gérante finit par entrer."""
    for _ in range(5):
        _login(client, company.slug, company.email, WRONG)

    owner_in = []
    for _ in range(6):
        clock.advance(30 * 60)
        _login(client, company.slug, company.email, WRONG)  # l'attaquant
        clock.advance(60)  # la gérante essaie une minute après lui
        owner_in.append(_login(client, company.slug, company.email, TEST_PASSWORD).status_code)
        if owner_in[-1] == 200:
            break

    assert 200 in owner_in, f"la gérante reste bloquée : {owner_in}"


@pytest.mark.usefixtures("redis_required", "throttle")
def test_a_parallel_burst_does_not_get_past_the_free_failures(
    company: DemoCompany, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) Vingt essais simultanés : au plus 5 vérifiés par Argon2, les autres freinés."""
    verified: list[int] = []
    lock = threading.Lock()

    def slow_verify(password: str, password_hash: str) -> bool:
        with lock:
            verified.append(1)
        time.sleep(0.3)
        return False

    monkeypatch.setattr(auth_service, "verify_password", slow_verify)

    def attempt(_: int) -> int:
        with TestClient(app, base_url=TEST_BASE_URL) as client:
            return int(_login(client, company.slug, company.email, WRONG).status_code)

    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(attempt, range(20)))

    assert len(verified) <= 5, f"{len(verified)} vérifications Argon2 pendant la rafale"
    assert statuses.count(429) >= 15


@pytest.mark.usefixtures("redis_required", "throttle")
def test_email_and_phone_of_one_account_share_one_counter(
    client: TestClient, company: DemoCompany, clock: _Clock
) -> None:
    """(c) Trois échecs par e-mail, deux par téléphone : le compte est freiné."""
    token = login_token(client, company)
    email = f"double-{uuid4().hex[:6]}@example.com"
    phone = "77" + str(uuid4().int)[:7]
    created = client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={"full_name": "Fatou Sow", "email": email, "phone": phone, "password": TEST_PASSWORD},
    )
    assert created.status_code == 201, created.text

    for _ in range(3):
        _login(client, company.slug, email, WRONG)
    for _ in range(2):
        _login(client, company.slug, phone, WRONG)

    assert _login(client, company.slug, email, TEST_PASSWORD).status_code == 429


class _BrokenRedis:
    def __getattr__(self, name: str) -> Any:
        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("Redis en panne (test)")

        return _raise


@pytest.fixture
def redis_switch(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, bool]]:
    """Redis allumé ou éteint à volonté, pour le frein comme pour le reste."""
    state = {"up": False}
    real = cache.get_client()
    broken = _BrokenRedis()

    def current() -> Any:
        return real if state["up"] else broken

    monkeypatch.setattr(rate_limit, "_redis", current)
    monkeypatch.setattr("app.core.cache.get_client", current)
    monkeypatch.setattr(rate_limit.sentry_sdk, "capture_message", lambda *a, **k: None)
    yield state


@pytest.mark.usefixtures("throttle")
def test_without_redis_a_flood_of_fake_identifiers_does_not_evict_the_victim(
    client: TestClient,
    company: DemoCompany,
    clock: _Clock,
    redis_switch: dict[str, bool],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(d) Réservoir de 3 clés : la victime freinée le reste malgré 10 identifiants inventés."""
    _small_memory(monkeypatch, 3)
    for _ in range(5):
        _login(client, company.slug, company.email, WRONG)
    for index in range(10):
        _login(client, company.slug, f"fantome-{index}@example.com", WRONG)

    assert _login(client, company.slug, company.email, TEST_PASSWORD).status_code == 429


@pytest.mark.usefixtures("redis_required", "throttle")
def test_failures_kept_in_memory_still_count_when_redis_comes_back(
    client: TestClient, company: DemoCompany, clock: _Clock, redis_switch: dict[str, bool]
) -> None:
    """(d) Cinq échecs pendant la panne ; Redis revient : l'attente tient toujours."""
    for _ in range(5):
        _login(client, company.slug, company.email, WRONG)

    redis_switch["up"] = True

    assert _login(client, company.slug, company.email, TEST_PASSWORD).status_code == 429
