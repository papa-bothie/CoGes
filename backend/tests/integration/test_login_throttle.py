"""Freinage progressif par compte et frein de connexion sans Redis (ADR 0078, A2-A3).

Barème : 5 échecs ⇒ 1 min d'attente, puis 2, 4, 8… minutes, 30 au plus ; remise à
zéro après un succès. Pendant l'attente : 429, `Retry-After`, même réponse que le
compte existe ou non, et le mot de passe n'est pas vérifié.

L'horloge est celle de `rate_limit._clock`, substituée : le barème se rejoue en quelques
millisecondes. Chaque test prend une entreprise neuve, donc des clés de compteur neuves.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core import cache, rate_limit
from app.core.config import get_settings
from app.modules.auth import service as auth_service
from tests.conftest import (
    TEST_PASSWORD,
    DemoCompany,
    _create_demo_company,
    read_scalar_in_tenant,
)

pytestmark = pytest.mark.integration

START = 1_800_000_000.0


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


@pytest.fixture
def throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Barème de production ; plafond par IP coupé pour isoler celui du compte."""
    settings = get_settings().model_copy(
        update={
            "login_throttle_free_failures": 5,
            "login_throttle_window_minutes": 15,
            "login_throttle_max_wait_minutes": 30,
            "login_throttle_alert_after": 10,
            "rate_limit_login_per_minute": 0,
        }
    )
    monkeypatch.setattr(rate_limit, "get_settings", lambda: settings)
    monkeypatch.setattr(auth_service, "get_settings", lambda: settings)
    monkeypatch.setattr(rate_limit, "_memory", rate_limit._MemoryCounters(10_000))
    monkeypatch.setattr(rate_limit, "_memory_accounts", rate_limit._MemoryAccounts(10_000))


@pytest.fixture
def redis_required() -> None:
    if cache.get_client() is None:
        pytest.skip("Redis requis")


@pytest.fixture
def company(app_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"lot-a2-{uuid4().hex[:8]}")


def _login(client: TestClient, slug: str, identifier: str, password: str) -> Any:
    return client.post(
        "/api/v1/auth/login",
        json={"company_slug": slug, "identifier": identifier, "password": password},
    )


def _fail(client: TestClient, company: DemoCompany, times: int, identifier: str = "") -> list[int]:
    who = identifier or company.email
    return [_login(client, company.slug, who, "mauvais-mot").status_code for _ in range(times)]


@pytest.mark.usefixtures("redis_required", "throttle")
def test_five_failures_then_one_minute_then_doubling_up_to_30(
    client: TestClient, company: DemoCompany, clock: _Clock
) -> None:
    assert _fail(client, company, 5) == [401] * 5

    blocked = _login(client, company.slug, company.email, TEST_PASSWORD)
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"
    assert blocked.json()["error"]["message"] == "Trop d'essais. Réessayez dans 1 minute."

    # Chaque nouvel échec, une fois l'attente passée, double la suivante — tant que les
    # échecs précédents ont moins de 45 min (fenêtre + attente maximale, ADR 0088).
    previous = 1
    for expected_minutes in (2, 4, 8, 16, 30):
        clock.advance(60 * previous + 1)
        assert _fail(client, company, 1) == [401]
        waiting = _login(client, company.slug, company.email, TEST_PASSWORD)
        assert waiting.status_code == 429
        assert int(waiting.headers["retry-after"]) == expected_minutes * 60
        assert f"Réessayez dans {expected_minutes} minutes." in waiting.json()["error"]["message"]
        previous = expected_minutes

    # Les échecs du début ont maintenant plus de 45 min : il n'en reste que deux, le
    # compte n'est plus freiné et la gérante entre.
    clock.advance(60 * 30 + 1)
    assert _fail(client, company, 1) == [401]
    assert _login(client, company.slug, company.email, TEST_PASSWORD).status_code == 200


@pytest.mark.usefixtures("redis_required", "throttle")
def test_waiting_does_not_check_the_password(
    client: TestClient, company: DemoCompany, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail(client, company, 5)
    calls: list[str] = []
    monkeypatch.setattr(
        auth_service, "verify_password", lambda *args: calls.append("argon2") or True
    )
    assert _login(client, company.slug, company.email, TEST_PASSWORD).status_code == 429
    assert calls == [], "aucun hachage Argon2 pendant l'attente"


@pytest.mark.usefixtures("redis_required", "throttle")
def test_same_answer_whether_the_account_exists_or_not(
    client: TestClient, company: DemoCompany, clock: _Clock
) -> None:
    ghost = f"personne-{uuid4().hex[:6]}@example.com"
    assert _fail(client, company, 5) == _fail(client, company, 5, ghost) == [401] * 5
    real = _login(client, company.slug, company.email, "mauvais-mot")
    unknown = _login(client, company.slug, ghost, "mauvais-mot")
    assert real.status_code == unknown.status_code == 429
    assert real.json() == unknown.json()
    assert real.headers["retry-after"] == unknown.headers["retry-after"]


@pytest.mark.usefixtures("redis_required", "throttle")
def test_a_success_resets_the_counter(
    client: TestClient, company: DemoCompany, clock: _Clock
) -> None:
    assert _fail(client, company, 4) == [401] * 4
    assert _login(client, company.slug, company.email, TEST_PASSWORD).status_code == 200
    assert _fail(client, company, 4) == [401] * 4, "le compteur repart de zéro"


@pytest.mark.usefixtures("redis_required", "throttle")
def test_the_window_forgets_old_failures(
    client: TestClient, company: DemoCompany, clock: _Clock
) -> None:
    """Un échec compte 45 min (fenêtre + attente maximale, ADR 0088), puis s'efface."""
    assert _fail(client, company, 4) == [401] * 4
    clock.advance(45 * 60 + 1)
    assert _fail(client, company, 4) == [401] * 4


@pytest.mark.usefixtures("redis_required", "throttle")
def test_no_personal_data_in_redis(client: TestClient, company: DemoCompany, clock: _Clock) -> None:
    _fail(client, company, 1)
    redis_client = cache.get_client()
    assert redis_client is not None
    keys = [str(k) for k in redis_client.scan_iter(f"{cache.NAMESPACE}:rl:acct:*")]
    assert keys, "la clé du compte est posée"
    assert not any(company.slug in k or company.email in k for k in keys)


@pytest.mark.usefixtures("redis_required", "throttle")
def test_the_tenth_failure_of_a_real_account_alerts_the_manager(
    client: TestClient,
    company: DemoCompany,
    clock: _Clock,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Any],
    workers_bound_to_test_database: None,
) -> None:
    queued: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        auth_service.queue,
        "enqueue",
        lambda name, **kwargs: queued.append((name, kwargs)) or True,
    )
    # Dix échecs en moins de 45 min, chacun à la fin de l'attente du précédent (ADR 0088).
    waits = [0, 0, 0, 0, 61, 121, 241, 481, 961, 0]
    for wait in waits:
        _fail(client, company, 1)
        clock.advance(wait)
    ghost = f"personne-{uuid4().hex[:6]}@example.com"
    for wait in waits:
        _fail(client, company, 1, ghost)
        clock.advance(wait)

    assert [name for name, _ in queued] == [auth_service.LOGIN_FAILURES_TASK], (
        "une seule demande d'alerte, pour le compte réel, au 10e échec"
    )
    _, kwargs = queued[0]
    assert kwargs["user_id"] == str(company.manager_id)
    assert kwargs["failures"] == 10

    from app.workers.tasks.notifications import LOGIN_FAILURES, login_failures

    assert LOGIN_FAILURES == auth_service.LOGIN_FAILURES_TASK
    payload = {k: kwargs[k] for k in ("company_id", "user_id", "failures")}
    assert login_failures(**payload) == 1
    assert login_failures(**{**payload, "failures": 11}) == 0, "une par heure au plus"

    title = read_scalar_in_tenant(
        session_factory,
        company.company_id,
        "SELECT title FROM notifications WHERE type = 'login_failures' AND user_id = :id",
        {"id": UUID(str(company.manager_id))},
    )
    assert title == "Plusieurs tentatives de connexion échouées sur le compte de Gérante de test"


@pytest.mark.usefixtures("redis_required", "throttle")
def test_an_expired_temporary_password_neither_fails_nor_resets(
    client: TestClient,
    company: DemoCompany,
    clock: _Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le bon provisoire, mais expiré : le compteur ne bouge pas (décision du lot)."""
    assert _fail(client, company, 4) == [401] * 4
    with monkeypatch.context() as patch:
        patch.setattr(auth_service, "_temporary_password_expired", lambda identity: True)
        for _ in range(3):
            expired = _login(client, company.slug, company.email, TEST_PASSWORD)
            assert expired.json()["error"]["code"] == "temporary_password_expired"
    # Toujours 4 échecs : le 5e déclenche l'attente.
    assert _fail(client, company, 1) == [401]
    assert _login(client, company.slug, company.email, TEST_PASSWORD).status_code == 429


# ------------------------------------------------------------------- sans Redis


class _BrokenRedis:
    def __getattr__(self, name: str) -> Any:
        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("Redis en panne (test)")

        return _raise


@pytest.fixture(params=["absent", "en panne"])
def no_redis(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    broken = None if request.param == "absent" else _BrokenRedis()
    monkeypatch.setattr(rate_limit, "_redis", lambda: broken)
    monkeypatch.setattr("app.core.cache.get_client", lambda: broken)
    reports: list[str] = []
    monkeypatch.setattr(
        rate_limit.sentry_sdk, "capture_message", lambda message, **kw: reports.append(message)
    )
    monkeypatch.setattr(rate_limit, "_degraded_reported_at", 0.0)
    yield
    assert reports, "le mode dégradé est signalé à Sentry"
    assert set(reports) == {"limitation de connexion en mode dégradé"}


@pytest.mark.usefixtures("throttle", "no_redis")
def test_without_redis_the_account_is_still_throttled(
    client: TestClient, company: DemoCompany, clock: _Clock
) -> None:
    assert _fail(client, company, 5) == [401] * 5
    blocked = _login(client, company.slug, company.email, TEST_PASSWORD)
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"


@pytest.mark.usefixtures("no_redis")
def test_without_redis_the_login_ip_cap_still_holds(
    client: TestClient, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings().model_copy(
        update={"rate_limit_login_per_minute": 2, "rate_limit_ip_per_minute": 2}
    )
    monkeypatch.setattr(rate_limit, "get_settings", lambda: settings)
    monkeypatch.setattr(rate_limit, "_memory", rate_limit._MemoryCounters(10_000))
    body = {"company_slug": "inconnue", "identifier": "x@example.com", "password": "mauvais"}
    login = [client.post("/api/v1/auth/login", json=body).status_code for _ in range(3)]
    assert login[2] == 429
    # Les autres routes gardent « limite désactivée » sans Redis, même au-delà du plafond.
    others = [client.get("/api/v1/health").status_code for _ in range(5)]
    assert others == [200] * 5


def test_degraded_reports_at_most_once_a_minute(
    clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports: list[str] = []
    monkeypatch.setattr(
        rate_limit.sentry_sdk, "capture_message", lambda message, **kw: reports.append(message)
    )
    monkeypatch.setattr(rate_limit, "_degraded_reported_at", 0.0)
    for _ in range(5):
        rate_limit._report_degraded()
    clock.advance(61)
    rate_limit._report_degraded()
    assert len(reports) == 2


def test_the_memory_counter_is_bounded_and_evicts_the_oldest(clock: _Clock) -> None:
    assert rate_limit._memory.capacity == 10_000
    counters = rate_limit._MemoryCounters(3)
    for key in ("a", "b", "c"):
        counters.incr(key, 60, clock.now)
    counters.incr("a", 60, clock.now)  # « a » redevient la plus récente
    counters.incr("d", 60, clock.now)  # évince « b », la plus ancienne
    assert len(counters) == 3
    assert counters.incr("b", 60, clock.now) == 1, "b avait été évincée"
    assert len(counters) == 3
