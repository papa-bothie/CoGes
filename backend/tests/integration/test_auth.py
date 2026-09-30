"""Authentification : connexion, rotation du refresh, détection de réutilisation."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.security import decode_access_token, hash_refresh_token
from app.core.tenancy import TenantContext, tenant_transaction
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


def _incidents(session_factory: sessionmaker[Any], company: DemoCompany) -> int:
    return read_scalar_in_tenant(
        session_factory,
        company.company_id,
        "SELECT count(*) FROM audit_logs "
        "WHERE entity_table = 'auth_sessions' AND action = 'cancel'",
    )


def _backdate_rotation(
    session_factory: sessionmaker[Any], company: DemoCompany, raw_token: str, seconds: int
) -> None:
    """Fait comme si la rotation de `raw_token` datait de `seconds` secondes."""
    ctx = TenantContext.bootstrap(company.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "UPDATE auth_sessions SET revoked_at = now() - make_interval(secs => :s) "
                "WHERE token_hash = :h"
            ),
            {"s": seconds, "h": hash_refresh_token(raw_token)},
        )


def test_replaying_a_token_whose_successor_was_used_revokes_the_whole_family(
    api_client: TestClient, company_alpha: DemoCompany, session_factory: sessionmaker[Any]
) -> None:
    """Rejouer un jeton déjà consommé, alors que son successeur a servi : vol, la famille tombe.

    La révocation doit **survivre** à l'échec de la requête : elle est commitée
    avant que l'erreur ne soit levée.
    """
    before = _incidents(session_factory, company_alpha)
    login = _login(api_client, company_alpha.slug, company_alpha.email, TEST_PASSWORD)
    stolen = login.cookies[REFRESH_COOKIE_NAME]

    assert api_client.post("/api/v1/auth/refresh").status_code == 200
    # La victime continue de travailler : le successeur a servi.
    again = api_client.post("/api/v1/auth/refresh")
    assert again.status_code == 200
    legitimate = again.cookies[REFRESH_COOKIE_NAME]

    # Le voleur rejoue l'ancien jeton, pourtant dans les 30 s.
    api_client.cookies.set(REFRESH_COOKIE_NAME, stolen)
    replayed = api_client.post("/api/v1/auth/refresh")
    assert replayed.status_code == 401
    assert replayed.json()["error"]["message"] == "Session révoquée."

    # La victime perd aussi sa session : toute la famille est révoquée.
    api_client.cookies.set(REFRESH_COOKIE_NAME, legitimate)
    assert api_client.post("/api/v1/auth/refresh").status_code == 401, (
        "le jeton légitime aurait dû être révoqué"
    )
    assert _incidents(session_factory, company_alpha) > before, "incident non audité"


def test_replaying_a_rotated_token_after_the_grace_window_revokes_the_family(
    api_client: TestClient, company_alpha: DemoCompany, session_factory: sessionmaker[Any]
) -> None:
    login = _login(api_client, company_alpha.slug, company_alpha.email, TEST_PASSWORD)
    old = login.cookies[REFRESH_COOKIE_NAME]
    rotated = api_client.post("/api/v1/auth/refresh")
    unreceived = rotated.cookies[REFRESH_COOKIE_NAME]
    _backdate_rotation(session_factory, company_alpha, old, seconds=31)

    api_client.cookies.set(REFRESH_COOKIE_NAME, old)
    assert api_client.post("/api/v1/auth/refresh").status_code == 401
    api_client.cookies.set(REFRESH_COOKIE_NAME, unreceived)
    assert api_client.post("/api/v1/auth/refresh").status_code == 401


def test_a_lost_rotation_response_is_retried_within_the_grace_window(
    api_client: TestClient, company_alpha: DemoCompany, session_factory: sessionmaker[Any]
) -> None:
    """ADR 0051 : la réponse de rotation s'est perdue (navigation, coupure réseau).

    Le client représente l'ancien jeton : il obtient une nouvelle session, le
    successeur jamais reçu est écarté, et la reprise est tracée sans révoquer la famille.
    """
    login = _login(api_client, company_alpha.slug, company_alpha.email, TEST_PASSWORD)
    old = login.cookies[REFRESH_COOKIE_NAME]
    lost = api_client.post("/api/v1/auth/refresh").cookies[REFRESH_COOKIE_NAME]
    _backdate_rotation(session_factory, company_alpha, old, seconds=25)

    api_client.cookies.set(REFRESH_COOKIE_NAME, old)
    retried = api_client.post("/api/v1/auth/refresh")
    assert retried.status_code == 200, retried.text
    fresh = retried.cookies[REFRESH_COOKIE_NAME]
    assert fresh not in (old, lost)

    # La nouvelle session vit…
    api_client.cookies.set(REFRESH_COOKIE_NAME, fresh)
    follow_up = api_client.post("/api/v1/auth/refresh")
    assert follow_up.status_code == 200

    retries = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs WHERE entity_table = 'auth_sessions' "
        "AND diff->'before'->>'reason' = 'rotation_retried_within_grace'",
    )
    assert retries >= 1, "la reprise n'a pas été tracée"


def test_a_grace_retry_is_granted_only_once(
    api_client: TestClient, company_alpha: DemoCompany
) -> None:
    """Le successeur écarté ne profite d'aucune grâce, et l'ancien jeton non plus une 2e fois."""
    login = _login(api_client, company_alpha.slug, company_alpha.email, TEST_PASSWORD)
    old = login.cookies[REFRESH_COOKIE_NAME]
    lost = api_client.post("/api/v1/auth/refresh").cookies[REFRESH_COOKIE_NAME]

    api_client.cookies.set(REFRESH_COOKIE_NAME, old)
    assert api_client.post("/api/v1/auth/refresh").status_code == 200

    # Le jeton jamais reçu, présenté par un tiers : réutilisation, la famille tombe.
    api_client.cookies.set(REFRESH_COOKIE_NAME, lost)
    assert api_client.post("/api/v1/auth/refresh").status_code == 401
    api_client.cookies.set(REFRESH_COOKIE_NAME, old)
    assert api_client.post("/api/v1/auth/refresh").status_code == 401


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
