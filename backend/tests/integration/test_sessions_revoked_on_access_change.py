"""Mot de passe changé ou compte coupé : les sessions de la personne tombent (P2.1, ADR 0088).

Un jeton de rafraîchissement volé ne doit pas survivre au geste qui devait justement
fermer la porte : nouveau mot de passe donné par le gérant, mot de passe changé par la
personne elle-même, compte désactivé ou supprimé.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import TEST_BASE_URL, TEST_PASSWORD, DemoCompany, auth_headers

pytestmark = pytest.mark.integration

NEW_PASSWORD = "nouveau-" + "z" * 12


@pytest.fixture
def victim(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> Iterator[tuple[TestClient, dict[str, Any]]]:
    """Un compte connecté dans son propre navigateur (son propre cookie)."""
    email = f"session-{uuid4().hex[:8]}@alpha.example.com"
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(alpha_token),
        json={"email": email, "full_name": "Moussa Diop", "password": TEST_PASSWORD},
    )
    assert created.status_code == 201, created.text
    with TestClient(app, base_url=TEST_BASE_URL) as browser:
        login = browser.post(
            "/api/v1/auth/login",
            json={"company_slug": company_alpha.slug, "email": email, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200, login.text
        yield browser, {"id": created.json()["id"], "token": login.json()["access_token"]}


def test_a_password_given_by_the_manager_ends_the_old_sessions(
    api_client: TestClient, alpha_token: str, victim: tuple[TestClient, dict[str, Any]]
) -> None:
    browser, account = victim
    reset = api_client.post(
        f"/api/v1/users/{account['id']}/password",
        headers=auth_headers(alpha_token),
        json={"new_password": NEW_PASSWORD},
    )
    assert reset.status_code == 200, reset.text

    assert browser.post("/api/v1/auth/refresh").status_code == 401


@pytest.mark.parametrize("gesture", ["delete", "deactivate"])
def test_a_closed_account_loses_its_sessions(
    api_client: TestClient,
    alpha_token: str,
    victim: tuple[TestClient, dict[str, Any]],
    gesture: str,
) -> None:
    browser, account = victim
    url = f"/api/v1/users/{account['id']}"
    if gesture == "delete":
        closed = api_client.delete(url, headers=auth_headers(alpha_token))
    else:
        closed = api_client.patch(url, headers=auth_headers(alpha_token), json={"is_active": False})
    assert closed.status_code == 200, closed.text

    assert browser.post("/api/v1/auth/refresh").status_code == 401


def test_changing_ones_own_password_ends_the_other_sessions_and_keeps_this_one(
    company_alpha: DemoCompany, victim: tuple[TestClient, dict[str, Any]]
) -> None:
    """Le jeton volé (autre navigateur) tombe ; celui de la personne continue de servir."""
    browser, account = victim
    email = browser.get("/api/v1/auth/me", headers=auth_headers(account["token"])).json()["user"][
        "email"
    ]
    with TestClient(app, base_url=TEST_BASE_URL) as thief:
        stolen = thief.post(
            "/api/v1/auth/login",
            json={"company_slug": company_alpha.slug, "email": email, "password": TEST_PASSWORD},
        )
        assert stolen.status_code == 200

        changed = browser.post(
            "/api/v1/auth/password",
            headers=auth_headers(account["token"]),
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert changed.status_code == 204, changed.text

        assert thief.post("/api/v1/auth/refresh").status_code == 401, "le jeton volé survit"
    assert browser.post("/api/v1/auth/refresh").status_code == 200, "la personne est déconnectée"
