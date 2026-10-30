"""Lectures de l'administration, lot admin 6 (ADR 0094).

Utilisateurs des commerçants en **lecture seule** (colonnes déjà accordées par 0026, jokers
échappés), journal de la plateforme sans aucun secret, profils dérivés du code, ce qui
demande une action, et filtre de statut des entreprises.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core import queue
from app.main import app
from app.modules.platform import capabilities
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    create_user_with_role,
    login_token,
)
from tests.integration.billing_harness import set_subscription
from tests.integration.platform_harness import (
    PlatformAccount,
    create_platform_account,
    platform_login,
)

USERS = "/api/v1/platform/users"
AUDIT = "/api/v1/platform/audit"


@pytest.fixture
def client(platform_bound_to_test_database: None) -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def administrator(platform_bound_to_test_database: None) -> PlatformAccount:
    return create_platform_account("administrator")


@pytest.fixture
def admin_headers(client: TestClient, administrator: PlatformAccount) -> dict[str, str]:
    return auth_headers(platform_login(client, administrator))


@pytest.fixture
def support_headers(client: TestClient) -> dict[str, str]:
    return auth_headers(platform_login(client, create_platform_account("support")))


@pytest.fixture(autouse=True)
def quiet_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "enqueue", lambda *_args, **_kwargs: True)


def _shop(prefix: str = "annuaire") -> DemoCompany:
    return _create_demo_company(f"{prefix}-{uuid4().hex[:8]}")


def _in_company(owner_engine: Engine, company_id: UUID, statement: str, **params: Any) -> None:
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :id, true)"), {"id": str(company_id)}
        )
        connection.execute(text(statement), {"company": company_id, **params})


# ------------------------------------------------------- utilisateurs commerçants

USER_KEYS = {
    "id",
    "full_name",
    "email",
    "company_id",
    "company_name",
    "roles",
    "status",
    "last_login_at",
}


def test_merchant_users_are_listed_read_only_with_their_company(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    shop = _shop()
    page = client.get(USERS, headers=admin_headers, params={"q": shop.slug}).json()
    assert set(page) == {"items", "page", "page_size", "total"}
    assert page["page_size"] == 20
    [manager] = page["items"]
    assert set(manager) == USER_KEYS
    assert manager == {
        "id": str(shop.manager_id),
        "full_name": "Gérante de test",
        "email": shop.email,
        "company_id": str(shop.company_id),
        "company_name": shop.slug.replace("-", " ").title(),
        "roles": ["gerant"],
        "status": "active",
        "last_login_at": None,
    }


def test_merchant_users_filter_by_role_status_and_company(
    client: TestClient, admin_headers: dict[str, str], owner_engine: Engine
) -> None:
    shop = _shop()
    token = login_token(client, shop)
    seller_email = f"vendeur@{shop.slug}.example.com"
    create_user_with_role(client, token, shop, role="vendeur", email=seller_email)
    login_token(client, shop)  # le gérant se reconnecte après le vendeur
    scoped = {"company_id": str(shop.company_id)}

    both = client.get(USERS, headers=admin_headers, params=scoped).json()
    assert both["total"] == 2
    sellers = client.get(USERS, headers=admin_headers, params={**scoped, "role": "vendeur"})
    assert [item["email"] for item in sellers.json()["items"]] == [seller_email]
    # La connexion du gérant est datée ; le tri par dernière connexion le met devant.
    recent = client.get(USERS, headers=admin_headers, params={**scoped, "sort": "-last_login"})
    assert recent.json()["items"][0]["email"] == shop.email
    by_name = client.get(USERS, headers=admin_headers, params={**scoped, "sort": "name"})
    names = [item["full_name"] for item in by_name.json()["items"]]
    assert names == sorted(names)

    _in_company(
        owner_engine,
        shop.company_id,
        "UPDATE users SET is_active = false, deactivated_at = now() "
        "WHERE company_id = :company AND email = :email",
        email=seller_email,
    )
    off = client.get(USERS, headers=admin_headers, params={**scoped, "status": "deactivated"})
    assert [item["email"] for item in off.json()["items"]] == [seller_email]

    suspended = client.patch(
        f"/api/v1/platform/companies/{shop.company_id}/status",
        headers=admin_headers,
        json={"status": "suspended", "reason": "Contrôle"},
    )
    assert suspended.status_code == 200
    cut = client.get(
        USERS, headers=admin_headers, params={**scoped, "status": "company_suspended"}
    ).json()
    # L'entreprise suspendue l'emporte sur l'état de chaque compte.
    assert sorted(item["email"] for item in cut["items"]) == sorted([shop.email, seller_email])
    assert {item["status"] for item in cut["items"]} == {"company_suspended"}


# Deux caractères : une recherche plus courte est ignorée (`normalise_term`).
@pytest.mark.parametrize("joker", ["%%", "e_", "\\%"])
def test_jokers_are_searched_literally(
    client: TestClient, admin_headers: dict[str, str], joker: str
) -> None:
    _shop()
    page = client.get(USERS, headers=admin_headers, params={"q": joker}).json()
    for item in page["items"]:
        assert any(joker in (item[key] or "") for key in ("full_name", "email", "company_name"))


@pytest.mark.parametrize(
    "params",
    [{"page_size": "101"}, {"sort": "password"}, {"status": "admin"}, {"q": "x" * 101}],
)
def test_impossible_user_filters_are_422(
    client: TestClient, admin_headers: dict[str, str], params: dict[str, str]
) -> None:
    assert client.get(USERS, headers=admin_headers, params=params).status_code == 422


def test_support_reads_merchant_users(client: TestClient, support_headers: dict[str, str]) -> None:
    assert client.get(USERS, headers=support_headers).status_code == 200


# ---------------------------------------------------------------------- journal

TRAP = "piege-a-secret-4f1c"


def test_the_journal_never_shows_a_secret(
    client: TestClient,
    admin_headers: dict[str, str],
    administrator: PlatformAccount,
    owner_engine: Engine,
) -> None:
    entity = uuid4()
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO platform_audit_logs (actor_id, action, entity_table, entity_id, diff) "
                "VALUES (:actor, 'update', 'platform_users', :entity, CAST(:diff AS jsonb))"
            ),
            {
                "actor": administrator.id,
                "entity": entity,
                "diff": (
                    '{"before": {"role": "support", "password_hash": "'
                    + TRAP
                    + '"}, "after": {"role": "administrator", "token": "'
                    + TRAP
                    + '", "token_hash": "'
                    + TRAP
                    + '", "nested": {"secret": "'
                    + TRAP
                    + '"}}, "reason": "Promotion", "password": "'
                    + TRAP
                    + '", "refresh_token": "'
                    + TRAP
                    + '"}'
                ),
            },
        )
    page = client.get(AUDIT, headers=admin_headers, params={"entity_id": str(entity)}).json()
    [entry] = page["items"]
    assert TRAP not in str(page)
    assert entry["diff"] == {
        "before": {"role": "support"},
        "after": {"role": "administrator"},
        "reason": "Promotion",
    }
    assert entry["actor_name"] == "Équipe administrator"


def test_the_journal_tells_who_did_what_to_whom(
    client: TestClient, admin_headers: dict[str, str], administrator: PlatformAccount
) -> None:
    colleague = create_platform_account("support")
    shop = _shop()
    client.patch(
        f"/api/v1/platform/team/{colleague.id}",
        headers=admin_headers,
        json={"role": "administrator"},
    )
    client.patch(
        f"/api/v1/platform/companies/{shop.company_id}/status",
        headers=admin_headers,
        json={"status": "suspended", "reason": "Impayé"},
    )

    on_colleague = client.get(
        AUDIT, headers=admin_headers, params={"entity_id": str(colleague.id), "action": "update"}
    ).json()
    [promotion] = on_colleague["items"]
    assert promotion["actor_id"] == str(administrator.id)
    assert promotion["entity_table"] == "platform_users"
    assert promotion["entity_name"] == "Équipe support"
    assert promotion["diff"] == {"before": {"role": "support"}, "after": {"role": "administrator"}}

    on_shop = client.get(
        AUDIT, headers=admin_headers, params={"company_id": str(shop.company_id)}
    ).json()
    assert {item["target_company_name"] for item in on_shop["items"]} == {
        shop.slug.replace("-", " ").title()
    }
    assert any(item["diff"].get("reason") == "Impayé" for item in on_shop["items"])

    by_actor = client.get(
        AUDIT, headers=admin_headers, params={"actor_id": str(administrator.id)}
    ).json()
    assert by_actor["items"]
    assert {item["actor_id"] for item in by_actor["items"]} == {str(administrator.id)}
    assert by_actor["page_size"] == 50


def test_the_journal_filters_by_period(client: TestClient, admin_headers: dict[str, str]) -> None:
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    future = client.get(AUDIT, headers=admin_headers, params={"start": tomorrow}).json()
    assert future["total"] == 0
    inverted = client.get(
        AUDIT, headers=admin_headers, params={"start": "2026-10-10", "end": "2026-10-01"}
    )
    assert inverted.status_code == 422


def test_support_cannot_read_the_journal(
    client: TestClient, support_headers: dict[str, str]
) -> None:
    assert client.get(AUDIT, headers=support_headers).status_code == 403


# ---------------------------------------------------------------------- profils


def test_profiles_and_their_capabilities_come_from_the_code(
    client: TestClient, support_headers: dict[str, str]
) -> None:
    body = client.get("/api/v1/platform/roles", headers=support_headers).json()
    assert [profile["role"] for profile in body] == ["administrator", "support"]
    keys = {profile["role"]: {c["key"] for c in profile["capabilities"]} for profile in body}
    assert "POST /api/v1/platform/team/invitations" in keys["administrator"]
    assert "POST /api/v1/platform/team/invitations" not in keys["support"]
    assert "GET /api/v1/platform/team" in keys["support"]
    assert "GET /api/v1/platform/audit" not in keys["support"]
    assert keys["support"] < keys["administrator"]
    for profile in body:
        assert profile["label"] and profile["description"]
        assert all(capability["label"] for capability in profile["capabilities"])


def test_every_platform_route_is_classed() -> None:
    """Registre : une route `/platform` qui exige un profil sans phrase fait échouer la CI,
    et une phrase sans route aussi."""
    unlabeled, stale = capabilities.registry_gaps(app.routes)
    assert unlabeled == [], f"Routes /platform sans capacité nommée : {unlabeled}"
    assert stale == [], f"Capacités sans route : {stale}"


# ----------------------------------------------------------------------- à traiter


def test_attention_lists_what_needs_doing(
    client: TestClient,
    admin_headers: dict[str, str],
    platform_session_factory: sessionmaker[Any],
) -> None:
    ending = _shop("fin-essai")
    later = _shop("essai-long")
    set_subscription(
        platform_session_factory,
        ending.company_id,
        trial_ends_at=datetime.now(UTC) + timedelta(days=3),
    )
    set_subscription(
        platform_session_factory,
        later.company_id,
        trial_ends_at=datetime.now(UTC) + timedelta(days=20),
    )
    cut = _shop("coupee")
    client.patch(
        f"/api/v1/platform/companies/{cut.company_id}/status",
        headers=admin_headers,
        json={"status": "suspended", "reason": "Contrôle"},
    )
    body = client.get("/api/v1/platform/attention", headers=admin_headers).json()
    assert set(body) == {
        "computed_at",
        "trials_ending",
        "suspended_companies",
        "suspended_total",
        "expiring_invitations",
        "security_events",
    }
    trials = {item["company_id"] for item in body["trials_ending"]}
    assert str(ending.company_id) in trials
    assert str(later.company_id) not in trials
    assert str(cut.company_id) in {item["company_id"] for item in body["suspended_companies"]}
    assert body["suspended_total"] >= 1


# ----------------------------------------------------------------- entreprises


def test_companies_filter_by_status(client: TestClient, admin_headers: dict[str, str]) -> None:
    cut = _shop("filtre")
    client.patch(
        f"/api/v1/platform/companies/{cut.company_id}/status",
        headers=admin_headers,
        json={"status": "suspended", "reason": "Contrôle"},
    )
    page = client.get(
        "/api/v1/platform/companies",
        headers=admin_headers,
        params={"status": "suspended", "page_size": "100"},
    ).json()
    assert {item["status"] for item in page["items"]} == {"suspended"}
    assert str(cut.company_id) in {item["id"] for item in page["items"]}
    bad = client.get(
        "/api/v1/platform/companies", headers=admin_headers, params={"status": "deleted"}
    )
    assert bad.status_code == 422
