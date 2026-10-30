"""Administration de la plateforme, lot 1 (ADR 0089) : connexion, entreprises, suspension."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core import queue
from app.core.tenancy import TenantContext, tenant_transaction
from app.main import app
from app.modules.platform import service as platform_service
from tests.conftest import (
    TEST_BASE_URL,
    TEST_PASSWORD,
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
    platform_login_response,
)


@pytest.fixture
def client(platform_bound_to_test_database: None) -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def administrator(platform_bound_to_test_database: None) -> PlatformAccount:
    return create_platform_account("administrator")


@pytest.fixture(scope="module")
def support(platform_bound_to_test_database: None) -> PlatformAccount:
    return create_platform_account("support")


@pytest.fixture
def shop(platform_bound_to_test_database: None) -> DemoCompany:
    """Entreprise neuve : la suspendre ne gêne aucun autre test."""
    return _create_demo_company(f"boutique-{uuid4().hex[:8]}")


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def _record(task_name: str, **kwargs: Any) -> bool:
        calls.append((task_name, kwargs))
        return True

    monkeypatch.setattr(queue, "enqueue", _record)
    return calls


def _suspend(client: TestClient, token: str, company_id: UUID, status: str = "suspended") -> Any:
    return client.patch(
        f"/api/v1/platform/companies/{company_id}/status",
        headers=auth_headers(token),
        json={"status": status, "reason": "Impayé depuis deux mois"},
    )


# ------------------------------------------------------------------- connexion


def test_an_administrator_logs_in_and_reads_who_they_are(
    client: TestClient, administrator: PlatformAccount
) -> None:
    token = platform_login(client, administrator)
    me = client.get("/api/v1/platform/auth/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["email"] == administrator.email
    assert me.json()["role"] == "administrator"


def test_wrong_password_and_unknown_email_answer_the_same(
    client: TestClient, administrator: PlatformAccount
) -> None:
    wrong = client.post(
        "/api/v1/platform/auth/login",
        json={"email": administrator.email, "password": "pas-le-bon-mot-de-passe"},
    )
    unknown = client.post(
        "/api/v1/platform/auth/login",
        json={"email": f"personne-{uuid4().hex[:6]}@example.com", "password": "x" * 12},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_a_merchant_cannot_log_into_the_administration(
    client: TestClient, company_alpha: DemoCompany
) -> None:
    response = client.post(
        "/api/v1/platform/auth/login",
        json={"email": company_alpha.email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 401


def test_refresh_rotates_and_a_replayed_token_revokes_the_family(
    client: TestClient, administrator: PlatformAccount
) -> None:
    login = platform_login_response(client, administrator)
    first = login.cookies["coges_platform_refresh"]

    rotated = client.post("/api/v1/platform/auth/refresh")
    assert rotated.status_code == 200
    second = rotated.cookies["coges_platform_refresh"]
    assert second != first

    # Le premier jeton, rejoué hors du délai de grâce par quelqu'un d'autre : on simule en
    # le présentant après que le second a servi.
    client.cookies.set("coges_platform_refresh", second, path="/api/v1/platform/auth")
    assert client.post("/api/v1/platform/auth/refresh").status_code == 200
    client.cookies.clear()
    client.cookies.set("coges_platform_refresh", first, path="/api/v1/platform/auth")
    assert client.post("/api/v1/platform/auth/refresh").status_code == 401
    # Toute la famille est tombée, dernier jeton compris.
    client.cookies.clear()
    client.cookies.set("coges_platform_refresh", second, path="/api/v1/platform/auth")
    assert client.post("/api/v1/platform/auth/refresh").status_code == 401


def test_logout_revokes_the_session(client: TestClient, administrator: PlatformAccount) -> None:
    platform_login(client, administrator)
    assert client.post("/api/v1/platform/auth/logout").status_code == 204
    assert client.post("/api/v1/platform/auth/refresh").status_code == 401


def test_a_deactivated_account_is_refused_at_once(
    client: TestClient, platform_session_factory: sessionmaker[Any]
) -> None:
    account = create_platform_account("support")
    token = platform_login(client, account)
    with platform_session_factory.begin() as session:
        session.execute(
            text("UPDATE platform_users SET is_active = false WHERE id = :id"), {"id": account.id}
        )
    assert client.get("/api/v1/platform/auth/me", headers=auth_headers(token)).status_code == 401
    assert client.post("/api/v1/platform/auth/refresh").status_code == 401


# ------------------------------------------------------------------ entreprises


SUMMARY_KEYS = {"id", "name", "slug", "status", "created_at", "user_count", "last_activity_at"}


def test_the_list_shows_metadata_and_nothing_else(
    client: TestClient, administrator: PlatformAccount, company_alpha: DemoCompany
) -> None:
    token = platform_login(client, administrator)
    response = client.get(
        "/api/v1/platform/companies",
        headers=auth_headers(token),
        params={"search": company_alpha.slug},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "page", "page_size", "total"}
    [item] = [row for row in body["items"] if row["slug"] == company_alpha.slug]
    assert set(item) == SUMMARY_KEYS
    # Toute entreprise naît en essai (ADR 0091).
    assert item["status"] == "trial"
    assert item["user_count"] >= 1


def test_the_detail_lists_the_accounts_of_the_company(
    client: TestClient, support: PlatformAccount, company_alpha: DemoCompany
) -> None:
    token = platform_login(client, support)
    response = client.get(
        f"/api/v1/platform/companies/{company_alpha.company_id}", headers=auth_headers(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == SUMMARY_KEYS | {"users"}
    manager = next(user for user in body["users"] if user["id"] == str(company_alpha.manager_id))
    assert set(manager) == {"id", "full_name", "roles", "is_active", "last_login_at"}
    assert "gerant" in manager["roles"]


def test_an_unknown_company_is_a_404(client: TestClient, support: PlatformAccount) -> None:
    token = platform_login(client, support)
    response = client.get(f"/api/v1/platform/companies/{uuid4()}", headers=auth_headers(token))
    assert response.status_code == 404


def test_search_wildcards_are_literal(client: TestClient, support: PlatformAccount) -> None:
    token = platform_login(client, support)
    response = client.get(
        "/api/v1/platform/companies", headers=auth_headers(token), params={"search": "%%"}
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


# ------------------------------------------------------------------- suspension


def test_support_cannot_suspend(
    client: TestClient, support: PlatformAccount, shop: DemoCompany
) -> None:
    token = platform_login(client, support)
    assert _suspend(client, token, shop.company_id).status_code == 403


def test_trial_is_never_a_target(
    client: TestClient, administrator: PlatformAccount, shop: DemoCompany
) -> None:
    token = platform_login(client, administrator)
    assert _suspend(client, token, shop.company_id, status="trial").status_code == 422


def test_suspension_cuts_access_at_the_next_request_then_reactivation_restores_it(
    client: TestClient,
    administrator: PlatformAccount,
    shop: DemoCompany,
    enqueued: list[tuple[str, dict[str, Any]]],
    platform_session_factory: sessionmaker[Any],
) -> None:
    merchant = login_token(client, shop)
    assert client.get("/api/v1/customers", headers=auth_headers(merchant)).status_code == 200

    token = platform_login(client, administrator)
    suspended = _suspend(client, token, shop.company_id)
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"

    # Le jeton émis avant la suspension ne sert plus, dès la requête suivante.
    refused = client.get("/api/v1/customers", headers=auth_headers(merchant))
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "company_suspended"
    assert "suspendu" in refused.json()["error"]["message"]

    # Le rafraîchissement aussi.
    assert client.post("/api/v1/auth/refresh").json()["error"]["code"] == "company_suspended"

    # Connexion : le bon mot de passe apprend la suspension, un mauvais n'apprend rien.
    login = client.post(
        "/api/v1/auth/login",
        json={"company_slug": shop.slug, "email": shop.email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 403
    assert login.json()["error"]["code"] == "company_suspended"
    wrong = client.post(
        "/api/v1/auth/login",
        json={"company_slug": shop.slug, "email": shop.email, "password": "mauvais-mot-de-passe"},
    )
    assert wrong.status_code == 401

    # Audit critique et e-mail au gérant, après COMMIT.
    with platform_session_factory.begin() as session:
        audit = session.execute(
            text(
                "SELECT actor_id, action, diff FROM platform_audit_logs "
                "WHERE target_company_id = :id ORDER BY id"
            ),
            {"id": shop.company_id},
        ).all()
    assert [(row.actor_id, row.action) for row in audit] == [(administrator.id, "update")]
    assert audit[0].diff["before"] == {"status": "trial"}
    assert audit[0].diff["after"] == {"status": "suspended"}
    assert audit[0].diff["reason"] == "Impayé depuis deux mois"
    assert enqueued == [
        (
            "platform.company_status_changed",
            {"countdown": 0, "company_id": str(shop.company_id), "status": "suspended"},
        )
    ]

    # Redemander le même statut ne change rien et ne prévient personne.
    assert _suspend(client, token, shop.company_id).status_code == 200
    assert len(enqueued) == 1

    reactivated = _suspend(client, token, shop.company_id, status="active")
    assert reactivated.json()["status"] == "active"
    assert client.get("/api/v1/customers", headers=auth_headers(merchant)).status_code == 200
    assert len(enqueued) == 2


def test_a_merchant_cannot_change_the_status_of_its_own_company(
    session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    """`coges_app` a UPDATE sur `companies` : la garde en base refuse le statut (CG006)."""
    ctx = TenantContext.bootstrap(shop.company_id)
    with (
        pytest.raises(DBAPIError, match="administration"),
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text("UPDATE companies SET status = 'suspended' WHERE id = :id"),
            {"id": shop.company_id},
        )


def test_a_refused_commit_keeps_the_status(
    administrator: PlatformAccount,
    shop: DemoCompany,
    owner_engine: Engine,
    enqueued: list[tuple[str, dict[str, Any]]],
    platform_bound_to_test_database: None,
) -> None:
    with TestClient(app, base_url=TEST_BASE_URL, raise_server_exceptions=False) as raw:
        token = platform_login(raw, administrator)
        enqueued.clear()  # l'alerte « nouvel appareil » de la connexion (ADR 0105)
        with failing_platform_commit(owner_engine):
            failed = _suspend(raw, token, shop.company_id)
        assert failed.status_code >= 500
        detail = raw.get(
            f"/api/v1/platform/companies/{shop.company_id}", headers=auth_headers(token)
        )
    assert detail.json()["status"] == "trial"
    assert enqueued == []


def test_the_cli_cuts_an_account_and_its_sessions(
    client: TestClient, platform_session_factory: sessionmaker[Any]
) -> None:
    account = create_platform_account("support")
    token = platform_login(client, account)
    assert platform_service.deactivate_platform_user(email=account.email.upper()) is True
    assert platform_service.deactivate_platform_user(email=account.email) is False
    assert client.get("/api/v1/platform/auth/me", headers=auth_headers(token)).status_code == 401
    assert client.post("/api/v1/platform/auth/refresh").status_code == 401
    with platform_session_factory.begin() as session:
        revoked = session.execute(
            text(
                "SELECT bool_and(revoked_at IS NOT NULL) FROM platform_auth_sessions "
                "WHERE platform_user_id = :id"
            ),
            {"id": account.id},
        ).scalar_one()
    assert revoked is True
