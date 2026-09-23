"""Authentification : connexion, rotation du refresh, détection de réutilisation."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import decode_access_token
from app.modules.auth.router import REFRESH_COOKIE_NAME
from tests.conftest import (
    TEST_PASSWORD,
    DemoCompany,
    auth_headers,
    login_token,
    read_scalar_in_tenant,
)

pytestmark = pytest.mark.integration


def _login(client: TestClient, slug: str, email: str, password: str):  # noqa: ANN202
    return client.post(
        "/api/v1/auth/login",
        json={"company_slug": slug, "email": email, "password": password},
    )


def test_login_returns_an_access_token_and_a_refresh_cookie(
    api_client: TestClient, company_alpha: DemoCompany
) -> None:
    response = _login(api_client, company_alpha.slug, company_alpha.email, TEST_PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    # Le refresh token n'est jamais dans le corps : il part en cookie httpOnly.
    assert "refresh_token" not in body
    assert REFRESH_COOKIE_NAME in response.cookies

    cookie_header = response.headers["set-cookie"]
    assert "httponly" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()


@pytest.mark.parametrize(
    ("case", "slug_source", "email_source", "password"),
    [
        ("mot de passe faux", "own", "own", "mauvais-mot-de-passe"),
        ("e-mail inconnu", "own", "inconnu@societe-alpha.example.com", TEST_PASSWORD),
        ("slug inconnu", "entreprise-qui-nexiste-pas", "own", TEST_PASSWORD),
    ],
)
def test_login_failures_are_indistinguishable(
    api_client: TestClient,
    company_alpha: DemoCompany,
    case: str,
    slug_source: str,
    email_source: str,
    password: str,
) -> None:
    """Aucune réponse ne permet de deviner si l'entreprise ou le compte existe."""
    slug = company_alpha.slug if slug_source == "own" else slug_source
    email = company_alpha.email if email_source == "own" else email_source

    response = _login(api_client, slug, email, password)

    assert response.status_code == 401, case
    assert response.json() == {
        "error": {
            "code": "authentication_required",
            "message": "Identifiants invalides.",
            "details": {},
        }
    }, case


def test_login_refuses_a_deactivated_account(
    api_client: TestClient, company_alpha: DemoCompany, alpha_token: str
) -> None:
    """Un compte désactivé donne exactement la même réponse qu'un mot de passe faux."""
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(alpha_token),
        json={
            "email": "inactif@societe-alpha.example.com",
            "full_name": "Compte inactif",
            "password": TEST_PASSWORD,
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    disabled = api_client.patch(
        f"/api/v1/users/{user_id}",
        headers=auth_headers(alpha_token),
        json={"is_active": False},
    )
    assert disabled.status_code == 200

    response = _login(
        api_client, company_alpha.slug, "inactif@societe-alpha.example.com", TEST_PASSWORD
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Identifiants invalides."


def test_same_email_in_two_companies_are_two_distinct_accounts(
    api_client: TestClient,
    company_alpha: DemoCompany,
    company_beta: DemoCompany,
    alpha_token: str,
    beta_token: str,
) -> None:
    """§ 2.2 : l'e-mail est unique **par entreprise**, jamais globalement."""
    shared_email = "partage@exemple.example.com"
    for token in (alpha_token, beta_token):
        created = api_client.post(
            "/api/v1/users",
            headers=auth_headers(token),
            json={
                "email": shared_email,
                "full_name": "Compte homonyme",
                "password": TEST_PASSWORD,
            },
        )
        assert created.status_code == 201, created.text

    alpha_login = _login(api_client, company_alpha.slug, shared_email, TEST_PASSWORD)
    beta_login = _login(api_client, company_beta.slug, shared_email, TEST_PASSWORD)

    assert alpha_login.status_code == 200
    assert beta_login.status_code == 200

    # Les deux comptes portent le même e-mail mais sont rattachés à deux
    # entreprises différentes : c'est le `company_id` du jeton qui le prouve.
    alpha_claims = decode_access_token(alpha_login.json()["access_token"])
    beta_claims = decode_access_token(beta_login.json()["access_token"])

    assert alpha_claims.company_id == company_alpha.company_id
    assert beta_claims.company_id == company_beta.company_id
    assert alpha_claims.user_id != beta_claims.user_id


def test_protected_route_requires_a_token(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/companies/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_refresh_rotates_the_token(api_client: TestClient, company_alpha: DemoCompany) -> None:
    login = _login(api_client, company_alpha.slug, company_alpha.email, TEST_PASSWORD)
    first_cookie = login.cookies[REFRESH_COOKIE_NAME]

    refreshed = api_client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200

    second_cookie = refreshed.cookies[REFRESH_COOKIE_NAME]
    assert second_cookie != first_cookie, "le refresh token n'a pas pivoté"
    assert refreshed.json()["access_token"]


def test_replaying_a_consumed_token_revokes_the_whole_family(
    api_client: TestClient, company_alpha: DemoCompany, session_factory: sessionmaker[Any]
) -> None:
    """Rejouer un jeton déjà consommé est le signe d'un vol : la famille tombe.

    La révocation doit **survivre** à l'échec de la requête : elle est commitée
    avant que l'erreur ne soit levée.
    """
    login = _login(api_client, company_alpha.slug, company_alpha.email, TEST_PASSWORD)
    stolen = login.cookies[REFRESH_COOKIE_NAME]

    rotated = api_client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    legitimate = rotated.cookies[REFRESH_COOKIE_NAME]

    # Le voleur rejoue l'ancien jeton.
    api_client.cookies.set(REFRESH_COOKIE_NAME, stolen)
    replayed = api_client.post("/api/v1/auth/refresh")
    assert replayed.status_code == 401
    assert replayed.json()["error"]["message"] == "Session révoquée."

    # La victime perd aussi sa session : toute la famille est révoquée.
    api_client.cookies.set(REFRESH_COOKIE_NAME, legitimate)
    victim = api_client.post("/api/v1/auth/refresh")
    assert victim.status_code == 401, "le jeton légitime aurait dû être révoqué"

    incidents = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs "
        "WHERE entity_table = 'auth_sessions' AND action = 'cancel'",
    )
    assert incidents >= 1, "l'incident de réutilisation n'a pas été audité"


def test_logout_revokes_the_session(api_client: TestClient, company_alpha: DemoCompany) -> None:
    _login(api_client, company_alpha.slug, company_alpha.email, TEST_PASSWORD)

    assert api_client.post("/api/v1/auth/logout").status_code == 204
    assert api_client.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_without_cookie_is_refused(api_client: TestClient) -> None:
    api_client.cookies.clear()
    response = api_client.post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_an_invalid_token_is_refused(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/companies/me", headers=auth_headers("pas-un-jeton-valide"))

    assert response.status_code == 401


def test_login_is_recorded_on_the_user(
    api_client: TestClient, company_alpha: DemoCompany, session_factory: sessionmaker[Any]
) -> None:
    """`last_login_at` est horodaté ; la connexion relève de l'audit asynchrone."""
    login_token(api_client, company_alpha)

    last_login = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT last_login_at FROM users WHERE id = :id",
        {"id": company_alpha.manager_id},
    )
    assert last_login is not None
