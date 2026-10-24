"""Accès support encadré (ADR 0092, révision 0029).

Le bris de glace ouvre un accès en lecture seule, borné dans le temps, tracé dans les
deux journaux. Le jeton passe par le chemin de tout utilisateur — `coges_app`, la RLS,
`SET LOCAL app.company_id` — et cesse de servir **à la requête suivante** dès que la
session est fermée ou échue. Aucune route d'écriture ne l'accepte.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, InternalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text
from starlette.requests import Request

from app.core import deps, mailer, queue, support_access
from app.core.security import AccessClaims, create_support_access_token
from app.core.tenancy import NIL_USER_ID, TenantContext, tenant_transaction
from app.main import app
from app.modules.platform import service as platform_service
from app.modules.rbac import matrix
from app.workers.tasks import platform as platform_tasks
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
)
from tests.integration.platform_harness import (
    PlatformAccount,
    create_platform_account,
    failing_platform_commit,
    platform_login,
)
from tests.integration.support_harness import close_support_session, open_support_session

pytestmark = pytest.mark.usefixtures("platform_bound_to_test_database")

WHY = "Le gérant signale par téléphone que sa caisse ne tombe pas juste"


@pytest.fixture
def client(platform_bound_to_test_database: None) -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def administrator(platform_bound_to_test_database: None) -> PlatformAccount:
    return create_platform_account("administrator")


@pytest.fixture(scope="module")
def supporter(platform_bound_to_test_database: None) -> PlatformAccount:
    return create_platform_account("support")


@pytest.fixture
def admin_headers(client: TestClient, administrator: PlatformAccount) -> dict[str, str]:
    return auth_headers(platform_login(client, administrator))


@pytest.fixture
def shop(platform_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"support-{uuid4().hex[:8]}")


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def _record(task_name: str, **kwargs: Any) -> bool:
        calls.append((task_name, kwargs))
        return True

    monkeypatch.setattr(queue, "enqueue", _record)
    return calls


def _open(client: TestClient, headers: dict[str, str], company_id: UUID, **body: Any) -> Any:
    return client.post(
        f"/api/v1/platform/companies/{company_id}/support-sessions",
        headers=headers,
        json={"justification": WHY, **body},
    )


def _company_journal(session_factory: sessionmaker[Any], company_id: UUID) -> list[Any]:
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        return list(
            session.execute(
                text(
                    "SELECT action, actor_user_id, entity_id, diff FROM audit_logs "
                    "WHERE entity_table = 'support_sessions' ORDER BY id"
                )
            )
        )


def _platform_journal(platform_session_factory: sessionmaker[Any], company_id: UUID) -> list[Any]:
    with platform_session_factory.begin() as session:
        return list(
            session.execute(
                text(
                    "SELECT action, actor_id FROM platform_audit_logs "
                    "WHERE target_company_id = :id AND entity_table = 'support_sessions' "
                    "ORDER BY id"
                ),
                {"id": company_id},
            )
        )


# ------------------------------------------------------------------ ouverture


@pytest.mark.parametrize(
    "body",
    [
        {"justification": ""},
        {"justification": "   court   "},
        {"duration_minutes": 241},
        {"duration_minutes": 29},
    ],
)
def test_a_break_glass_needs_a_reason_and_a_bounded_duration(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany, body: dict[str, Any]
) -> None:
    response = _open(client, admin_headers, shop.company_id, **body)
    assert response.status_code == 422, response.text


def test_opening_writes_both_journals_and_warns_the_manager(
    client: TestClient,
    admin_headers: dict[str, str],
    administrator: PlatformAccount,
    shop: DemoCompany,
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    response = _open(client, admin_headers, shop.company_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"session", "access_token", "token_type", "expires_in"}
    session = body["session"]
    assert session["justification"] == WHY
    assert session["is_open"] and session["opened_by_me"]
    started = datetime.fromisoformat(session["started_at"])
    expires = datetime.fromisoformat(session["expires_at"])
    assert expires - started == timedelta(hours=2)  # 2 h par défaut
    assert 7000 < body["expires_in"] <= 7200

    [opened] = _company_journal(session_factory, shop.company_id)
    assert (opened.action, opened.actor_user_id) == ("insert", None)  # « l'équipe CoGes »
    assert str(opened.entity_id) == session["id"]
    assert opened.diff["after"]["justification"] == WHY
    assert [tuple(row) for row in _platform_journal(platform_session_factory, shop.company_id)] == [
        ("insert", administrator.id)
    ]
    assert [name for name, _ in enqueued] == [platform_service.SUPPORT_NOTICE_TASK]


def test_the_support_profile_may_open_too(
    client: TestClient, supporter: PlatformAccount, shop: DemoCompany
) -> None:
    headers = auth_headers(platform_login(client, supporter))
    assert _open(client, headers, shop.company_id, duration_minutes=30).status_code == 201


def test_one_open_session_per_company(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany
) -> None:
    assert _open(client, admin_headers, shop.company_id).status_code == 201
    again = _open(client, admin_headers, shop.company_id)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "support_session_already_open"


def test_an_expired_session_does_not_block_a_new_one(
    client: TestClient,
    admin_headers: dict[str, str],
    administrator: PlatformAccount,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    open_support_session(
        platform_session_factory,
        shop.company_id,
        administrator.id,
        started_at=datetime.now(UTC) - timedelta(hours=3),
    )
    assert _open(client, admin_headers, shop.company_id).status_code == 201


def test_a_suspended_company_gets_no_support_session(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    _suspend(platform_session_factory, shop.company_id)
    response = _open(client, admin_headers, shop.company_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "support_company_suspended"


def test_an_unknown_company_is_not_found(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert _open(client, admin_headers, uuid4()).status_code == 404


def _suspend(platform_session_factory: sessionmaker[Any], company_id: UUID) -> None:
    with platform_session_factory.begin() as session:
        session.execute(
            text(
                """
                UPDATE companies SET status = 'suspended' WHERE id = :id
                """
            ),
            {"id": company_id},
        )


# ------------------------------------------------------------------ lecture


def test_the_token_reads_the_company_like_a_user(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany
) -> None:
    manager = auth_headers(login_token(client, shop))
    created = client.post("/api/v1/categories", headers=manager, json={"name": "Boissons"})
    assert created.status_code == 201, created.text

    token = _open(client, admin_headers, shop.company_id).json()["access_token"]
    categories = client.get("/api/v1/categories", headers=auth_headers(token))
    assert categories.status_code == 200, categories.text
    assert [item["name"] for item in categories.json()["items"]] == ["Boissons"]

    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()
    assert me["via_support"] is True
    assert me["user"]["full_name"] == support_access.DISPLAY_NAME
    assert [role["name"] for role in me["roles"]] == ["support_readonly"]
    assert me["permissions"] == sorted(support_access.PERMISSIONS)
    assert me["company"]["id"] == str(shop.company_id)


def test_the_support_token_reaches_nothing_of_another_company(
    client: TestClient,
    administrator: PlatformAccount,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    other = _create_demo_company(f"support-b-{uuid4().hex[:8]}")
    other_manager = auth_headers(login_token(client, other))
    category = client.post("/api/v1/categories", headers=other_manager, json={"name": "Riz B"})
    assert category.status_code == 201, category.text
    _, token = open_support_session(platform_session_factory, shop.company_id, administrator.id)

    response = client.get(
        f"/api/v1/categories/{category.json()['id']}", headers=auth_headers(token)
    )
    assert response.status_code == 404
    listing = client.get("/api/v1/categories", headers=auth_headers(token)).json()
    assert listing["items"] == []


def test_a_session_of_another_company_does_not_open_this_one(
    client: TestClient,
    administrator: PlatformAccount,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    """Un jeton dont la session appartient à A mais qui viserait B : rien (RLS)."""
    other = _create_demo_company(f"support-c-{uuid4().hex[:8]}")
    session_id, _ = open_support_session(
        platform_session_factory, shop.company_id, administrator.id
    )
    forged, _ = create_support_access_token(
        session_id, other.company_id, datetime.now(UTC) + timedelta(hours=1)
    )
    response = client.get("/api/v1/categories", headers=auth_headers(forged))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "support_session_ended"


# ------------------------------------------------------- fin de la session


def test_a_closed_session_is_refused_at_the_next_request(
    client: TestClient,
    admin_headers: dict[str, str],
    administrator: PlatformAccount,
    shop: DemoCompany,
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
) -> None:
    opened = _open(client, admin_headers, shop.company_id).json()
    token = auth_headers(opened["access_token"])
    assert client.get("/api/v1/categories", headers=token).status_code == 200

    closed = client.delete(
        f"/api/v1/platform/support-sessions/{opened['session']['id']}", headers=admin_headers
    )
    assert closed.status_code == 204, closed.text
    refused = client.get("/api/v1/categories", headers=token)
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "support_session_ended"

    assert [row.action for row in _company_journal(session_factory, shop.company_id)] == [
        "insert",
        "update",
    ]
    assert [row.action for row in _platform_journal(platform_session_factory, shop.company_id)] == [
        "insert",
        "update",
    ]
    again = client.delete(
        f"/api/v1/platform/support-sessions/{opened['session']['id']}", headers=admin_headers
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "support_session_closed"


def test_an_expired_session_is_refused_even_with_a_living_token(
    client: TestClient,
    administrator: PlatformAccount,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    """La base fait foi, pas l'échéance du jeton : relue à chaque requête."""
    _, token = open_support_session(
        platform_session_factory,
        shop.company_id,
        administrator.id,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        duration=timedelta(hours=1),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    response = client.get("/api/v1/categories", headers=auth_headers(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "support_session_ended"


def test_the_token_stops_at_the_session_end_without_any_action(
    client: TestClient,
    administrator: PlatformAccount,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    _, token = open_support_session(
        platform_session_factory,
        shop.company_id,
        administrator.id,
        started_at=datetime.now(UTC) - timedelta(minutes=30),
        duration=timedelta(minutes=30, seconds=2),
    )
    assert client.get("/api/v1/categories", headers=auth_headers(token)).status_code == 200
    time.sleep(2.5)
    assert client.get("/api/v1/categories", headers=auth_headers(token)).status_code == 401


def test_a_suspended_company_refuses_the_support_token_too(
    client: TestClient,
    administrator: PlatformAccount,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    _, token = open_support_session(platform_session_factory, shop.company_id, administrator.id)
    _suspend(platform_session_factory, shop.company_id)
    response = client.get("/api/v1/categories", headers=auth_headers(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "company_suspended"


def test_the_night_closes_expired_sessions_at_their_end(
    administrator: PlatformAccount,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    session_id, _ = open_support_session(
        platform_session_factory,
        shop.company_id,
        administrator.id,
        started_at=datetime.now(UTC) - timedelta(hours=3),
    )
    assert platform_service.close_expired_support_sessions() >= 1
    with platform_session_factory.begin() as session:
        row = session.execute(
            text("SELECT ended_at, expires_at, ended_by FROM support_sessions WHERE id = :id"),
            {"id": session_id},
        ).one()
    assert (row.ended_at, row.ended_by) == (row.expires_at, None)
    assert platform_service.close_expired_support_sessions() == 0  # relancée : sans effet


# ------------------------------------------------------- jeton redonné


def test_the_opener_gets_the_token_again_and_no_one_else(
    client: TestClient,
    admin_headers: dict[str, str],
    supporter: PlatformAccount,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    session_id = _open(client, admin_headers, shop.company_id).json()["session"]["id"]
    url = f"/api/v1/platform/support-sessions/{session_id}/token"
    again = client.post(url, headers=admin_headers)
    assert again.status_code == 200, again.text
    assert (
        client.get(
            "/api/v1/categories", headers=auth_headers(again.json()["access_token"])
        ).status_code
        == 200
    )

    other = client.post(url, headers=auth_headers(platform_login(client, supporter)))
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "support_session_not_yours"

    client.delete(f"/api/v1/platform/support-sessions/{session_id}", headers=admin_headers)
    assert client.post(url, headers=admin_headers).status_code == 409


def test_the_list_shows_the_open_session_then_none(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany
) -> None:
    url = f"/api/v1/platform/companies/{shop.company_id}/support-sessions"
    assert client.get(url, headers=admin_headers).json() == {"active": None, "recent": []}
    session_id = _open(client, admin_headers, shop.company_id).json()["session"]["id"]
    listed = client.get(url, headers=admin_headers).json()
    assert listed["active"]["id"] == session_id
    assert listed["active"]["opened_by"] == "Équipe administrator"
    client.delete(f"/api/v1/platform/support-sessions/{session_id}", headers=admin_headers)
    listed = client.get(url, headers=admin_headers).json()
    assert listed["active"] is None
    assert [item["is_open"] for item in listed["recent"]] == [False]


# ------------------------------------------------------- lecture seule


def _depends_on_tenant(route: APIRoute) -> bool:
    stack = list(route.dependant.dependencies)
    while stack:
        dependant = stack.pop()
        if dependant.call is deps.get_tenant_session:
            return True
        stack.extend(dependant.dependencies)
    return False


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
#: Écritures sans jeton commerçant : la connexion (cookie ou identifiants) et
#: l'administration (son propre jeton). Un jeton de support n'y ouvre rien.
TOKENLESS_WRITES = {
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
}


def _routes(routes: Iterable[Any], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Routes de l'application avec leur chemin complet, routeurs inclus compris."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _routes(nested.routes, prefix + route.include_context.prefix)


def _tenant_writes() -> list[tuple[str, str]]:
    writes = []
    for path, route in _routes(app.routes):
        for method in sorted(route.methods & WRITE_METHODS):
            if _depends_on_tenant(route):
                writes.append((method, path))
            else:
                assert path in TOKENLESS_WRITES or path.startswith("/api/v1/platform/"), (
                    f"écriture sans contexte tenant inattendue : {method} {path}"
                )
    return writes


TENANT_WRITES = _tenant_writes()


def test_the_write_routes_are_all_found() -> None:
    assert len(TENANT_WRITES) > 40
    assert ("POST", "/api/v1/sales/{sale_id}/confirm") in TENANT_WRITES


@pytest.fixture(scope="module")
def support_token(
    platform_bound_to_test_database: None, platform_session_factory: sessionmaker[Any]
) -> str:
    company = _create_demo_company(f"support-ecrit-{uuid4().hex[:8]}")
    account = create_platform_account("support")
    _, token = open_support_session(platform_session_factory, company.company_id, account.id)
    return token


@pytest.mark.parametrize(("method", "path"), TENANT_WRITES)
def test_no_write_route_accepts_the_support_token(
    method: str, path: str, client: TestClient, support_token: str
) -> None:
    concrete = path
    while "{" in concrete:
        start = concrete.index("{")
        concrete = concrete[:start] + str(uuid4()) + concrete[concrete.index("}") + 1 :]
    response = client.request(
        method,
        concrete,
        headers={**auth_headers(support_token), "Idempotency-Key": uuid4().hex},
        json={},
    )
    assert response.status_code == 403, f"{method} {path} : {response.status_code}"
    assert response.json()["error"]["code"] == "support_read_only"


def test_the_transaction_itself_refuses_writes(
    administrator: PlatformAccount,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    """Troisième verrou : même une écriture qu'aucune permission n'arrêterait, la base la
    refuse, sur la session même que la dépendance ouvre."""
    session_id, _ = open_support_session(
        platform_session_factory, shop.company_id, administrator.id
    )
    claims = AccessClaims(
        user_id=NIL_USER_ID,
        company_id=shop.company_id,
        token_id=uuid4(),
        support_session_id=session_id,
    )
    request = Request({"type": "http", "method": "GET", "headers": [], "path": "/"})
    request.state.tenant = None
    dependency = deps.get_tenant_session(request, claims)
    tenant = next(dependency)
    assert tenant.ctx.is_support
    with pytest.raises((InternalError, DBAPIError), match="read-only transaction"):
        tenant.session.execute(
            text("INSERT INTO categories (company_id, name) VALUES (:company_id, 'Interdit')"),
            {"company_id": shop.company_id},
        )
    with pytest.raises(RuntimeError):  # rend la session : rollback, rien d'écrit
        dependency.throw(RuntimeError("fin du test"))


def test_the_support_role_is_reads_only_and_never_in_the_database(
    owner_engine: Engine,
) -> None:
    with owner_engine.connect() as connection:
        catalogue = set(connection.execute(text("SELECT code FROM permissions")).scalars())
        stored = connection.execute(
            text("SELECT count(*) FROM roles WHERE name = :name"), {"name": matrix.SUPPORT_READONLY}
        ).scalar_one()
    assert catalogue >= matrix.SUPPORT_READONLY_PERMISSIONS
    assert all(code.endswith(":read") for code in matrix.SUPPORT_READONLY_PERMISSIONS)
    assert "notifications:read" not in matrix.SUPPORT_READONLY_PERMISSIONS
    assert matrix.SUPPORT_READONLY not in matrix.SYSTEM_ROLES
    assert stored == 0


# ------------------------------------------------------- côté entreprise


def test_every_user_sees_the_banner_then_nothing(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany
) -> None:
    manager = auth_headers(login_token(client, shop))
    url = "/api/v1/companies/me/support-access"
    assert client.get(url, headers=manager).json() == {"session": None}

    opened = _open(client, admin_headers, shop.company_id).json()["session"]
    banner = client.get(url, headers=manager).json()["session"]
    assert set(banner) == {"started_at", "expires_at"}  # ni qui, ni pourquoi
    assert banner["expires_at"] == opened["expires_at"]
    support = auth_headers(_reissue(client, admin_headers, opened["id"]))
    assert client.get(url, headers=support).json()["session"] is not None

    client.delete(f"/api/v1/platform/support-sessions/{opened['id']}", headers=admin_headers)
    assert client.get(url, headers=manager).json() == {"session": None}


def _reissue(client: TestClient, headers: dict[str, str], session_id: str) -> str:
    response = client.post(f"/api/v1/platform/support-sessions/{session_id}/token", headers=headers)
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def test_the_company_reads_five_columns_of_its_own_sessions_only(
    administrator: PlatformAccount,
    shop: DemoCompany,
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
) -> None:
    open_support_session(platform_session_factory, shop.company_id, administrator.id)
    other = _create_demo_company(f"support-d-{uuid4().hex[:8]}")
    with tenant_transaction(
        TenantContext.bootstrap(other.company_id), session_factory=session_factory
    ) as session:
        assert session.execute(text("SELECT count(*) FROM support_sessions")).scalar_one() == 0
    with (
        pytest.raises(DBAPIError, match="permission denied"),
        tenant_transaction(
            TenantContext.bootstrap(shop.company_id), session_factory=session_factory
        ) as session,
    ):
        session.execute(text("SELECT justification FROM support_sessions"))


def test_a_session_changes_once_to_be_closed(
    administrator: PlatformAccount,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    session_id, _ = open_support_session(
        platform_session_factory, shop.company_id, administrator.id
    )
    close_support_session(platform_session_factory, session_id)
    with pytest.raises(DBAPIError, match="ne change que pour être fermée"):
        close_support_session(platform_session_factory, session_id)


# ------------------------------------------------------- le gérant prévenu


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    mails: list[dict[str, Any]] = []

    def _send(**message: Any) -> bool:
        mails.append(message)
        return True

    monkeypatch.setattr(mailer, "send_email", _send)
    return mails


@pytest.mark.usefixtures("workers_bound_to_test_database")
def test_the_manager_is_warned_once_by_bell_and_mail(
    administrator: PlatformAccount,
    shop: DemoCompany,
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    sent: list[dict[str, Any]],
) -> None:
    session_id, _ = open_support_session(
        platform_session_factory, shop.company_id, administrator.id
    )
    expires = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    args = (str(shop.company_id), str(session_id), expires)
    assert platform_tasks.support_notice(*args) is True
    assert platform_tasks.support_notice(*args) is False
    with tenant_transaction(
        TenantContext.bootstrap(shop.company_id), session_factory=session_factory
    ) as session:
        titles = list(
            session.execute(
                text("SELECT title FROM notifications WHERE type = 'support_access'")
            ).scalars()
        )
    assert titles == ["L'équipe CoGes consulte votre boutique"]
    [mail] = sent
    assert mail["to"] == [shop.email]
    assert "Le gérant signale un écart de caisse" in mail["body"]
    assert "lecture seule" in mail["body"]


def test_the_company_history_tells_the_access_with_its_reason(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany
) -> None:
    session_id = _open(client, admin_headers, shop.company_id).json()["session"]["id"]
    client.delete(f"/api/v1/platform/support-sessions/{session_id}", headers=admin_headers)
    manager = auth_headers(login_token(client, shop))
    lines = client.get("/api/v1/analytics/history", headers=manager).json()["items"]
    told = [line["sentence"] for line in lines if "accès support" in line["sentence"]]
    assert told == [
        "L’équipe CoGes a fermé son accès support",
        f"L’équipe CoGes a ouvert un accès support, en lecture seule. Motif : « {WHY} »",
    ]
    assert {line["initials"] for line in lines if "accès support" in line["sentence"]} == {"CG"}


# ------------------------------------------------------- COMMIT refusé


def _open_rows(platform_session_factory: sessionmaker[Any], company_id: UUID) -> list[Any]:
    with platform_session_factory.begin() as session:
        return list(
            session.execute(
                text("SELECT id, ended_at FROM support_sessions WHERE company_id = :id"),
                {"id": company_id},
            )
        )


def test_a_refused_commit_gives_no_token(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    owner_engine: Engine,
    platform_session_factory: sessionmaker[Any],
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    """Le journal de l'administration refuse son COMMIT : aucune session, aucun jeton, aucun
    e-mail. (Celui de l'entreprise, validé avant, peut garder la tentative : ADR 0092.)"""
    with failing_platform_commit(owner_engine):
        response = _open(client, admin_headers, shop.company_id)
    assert response.status_code == 500
    assert "access_token" not in response.text
    assert _open_rows(platform_session_factory, shop.company_id) == []
    assert enqueued == []


def test_a_refused_close_keeps_the_session(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    owner_engine: Engine,
    platform_session_factory: sessionmaker[Any],
) -> None:
    opened = _open(client, admin_headers, shop.company_id).json()
    with failing_platform_commit(owner_engine):
        response = client.delete(
            f"/api/v1/platform/support-sessions/{opened['session']['id']}", headers=admin_headers
        )
    assert response.status_code == 500
    [row] = _open_rows(platform_session_factory, shop.company_id)
    assert row.ended_at is None
    token = auth_headers(opened["access_token"])
    assert client.get("/api/v1/categories", headers=token).status_code == 200
