"""Deux familles de jetons, jamais interchangeables (ADR 0089).

Toutes les routes sont énumérées depuis l'OpenAPI : une route ajoutée demain entre
dans le test sans que personne y pense.

* un jeton de l'administration n'ouvre **aucune** route commerçante (`/api/v1/*`) ;
* un jeton commerçant n'ouvre **aucune** route de l'administration (`/api/v1/platform/*`) ;
* sans jeton, les deux familles répondent 401.

Jamais de donnée dans la réponse : le corps est l'enveloppe d'erreur, rien d'autre.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import TEST_BASE_URL, DemoCompany, auth_headers, login_token
from tests.integration.platform_harness import create_platform_account, platform_login

pytestmark = pytest.mark.tenancy

PLATFORM_PREFIX = "/api/v1/platform/"

#: Routes sans compte : santé, et les trois gestes de session qui n'ont pas de jeton
#: d'accès à présenter (connexion, rafraîchissement par cookie, déconnexion).
OPEN_PATHS = frozenset(
    {
        "/api/v1/health",
        "/api/v1/health/ready",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/platform/auth/login",
        "/api/v1/platform/auth/refresh",
        "/api/v1/platform/auth/logout",
    }
)
#: Protégée par `COGES_OPS_TOKEN` : 404 sans jeton configuré, 401 sinon (ADR 0077).
OPS_PATHS = frozenset({"/api/v1/system/workers"})


def _operations() -> list[tuple[str, str]]:
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if path not in OPEN_PATHS and method in ("get", "post", "put", "patch", "delete")
    )


TENANT_ROUTES = [op for op in _operations() if not op[1].startswith(PLATFORM_PREFIX)]
PLATFORM_ROUTES = [op for op in _operations() if op[1].startswith(PLATFORM_PREFIX)]


def _concrete(path: str) -> str:
    return re.sub(
        r"\{[^}]+\}", lambda m: "products" if m.group(0) == "{kind}" else str(uuid4()), path
    )


def _call(client: TestClient, method: str, path: str, headers: dict[str, str]) -> object:
    return client.request(
        method, _concrete(path), headers={**headers, "Idempotency-Key": uuid4().hex}, json={}
    )


def _assert_refused(response: object, path: str) -> None:
    status = response.status_code  # type: ignore[attr-defined]
    allowed = {401, 404} if path in OPS_PATHS else {401}
    assert status in allowed, f"{path} → {status} {response.text}"  # type: ignore[attr-defined]
    assert set(response.json()) == {"error"}  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def client(platform_bound_to_test_database: None) -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def platform_token(client: TestClient) -> str:
    return platform_login(client, create_platform_account("administrator"))


@pytest.fixture(scope="module")
def merchant_token(client: TestClient, company_alpha: DemoCompany) -> str:
    return login_token(client, company_alpha)


def test_both_families_are_not_empty() -> None:
    assert len(TENANT_ROUTES) > 50
    assert {path for _, path in PLATFORM_ROUTES} >= {
        "/api/v1/platform/auth/me",
        "/api/v1/platform/companies",
        "/api/v1/platform/companies/{company_id}",
        "/api/v1/platform/companies/{company_id}/status",
    }


@pytest.mark.parametrize(
    ("method", "path"), TENANT_ROUTES, ids=[f"{m} {p}" for m, p in TENANT_ROUTES]
)
def test_a_platform_token_opens_no_merchant_route(
    client: TestClient, platform_token: str, method: str, path: str
) -> None:
    _assert_refused(_call(client, method, path, auth_headers(platform_token)), path)


@pytest.mark.parametrize(
    ("method", "path"), PLATFORM_ROUTES, ids=[f"{m} {p}" for m, p in PLATFORM_ROUTES]
)
def test_a_merchant_token_opens_no_platform_route(
    client: TestClient, merchant_token: str, method: str, path: str
) -> None:
    _assert_refused(_call(client, method, path, auth_headers(merchant_token)), path)


@pytest.mark.parametrize(
    ("method", "path"), _operations(), ids=[f"{m} {p}" for m, p in _operations()]
)
def test_without_a_token_every_route_answers_401(
    client: TestClient, method: str, path: str
) -> None:
    _assert_refused(_call(client, method, path, {}), path)
