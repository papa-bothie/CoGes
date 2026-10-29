"""Cloudflare Access devant l'administration, par l'application entière (ADR 0104).

Avec `COGES_ACCESS_TEAM_DOMAIN` et `COGES_ACCESS_AUD`, toute route `/api/v1/platform/*`
exige un jeton Cloudflare Access valide, avant même le mot de passe : un bon mot de passe
sans jeton est refusé. Les routes commerçantes ne changent pas. Sans configuration, rien
n'est contrôlé.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.cloudflare_access import get_access_verifier
from app.core.config import get_settings
from app.main import app
from tests.conftest import TEST_BASE_URL
from tests.helpers.access_tokens import AUD, KEY, OTHER_KEY, TEAM, jwk, token
from tests.integration.platform_harness import PLATFORM_PASSWORD, create_platform_account

pytestmark = pytest.mark.integration

HEADER = "Cf-Access-Jwt-Assertion"


def _clear() -> None:
    get_settings.cache_clear()
    get_access_verifier.cache_clear()


@pytest.fixture
def access(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("COGES_ACCESS_TEAM_DOMAIN", TEAM)
    monkeypatch.setenv("COGES_ACCESS_AUD", AUD)
    _clear()
    verifier = get_access_verifier()
    assert verifier is not None
    verifier.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"keys": [jwk(KEY, "k1")]})
        )
    )
    yield
    _clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL) as test_client:
        yield test_client


def _refused(response: httpx.Response) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "access_required"


@pytest.mark.usefixtures("access")
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {HEADER: ""},
        {HEADER: token(OTHER_KEY)},
        {HEADER: token(aud=["b" * 64])},
        {HEADER: token(exp=1)},
    ],
    ids=["absent", "vide", "autre-cle", "autre-aud", "expire"],
)
def test_the_caddy_probe_refuses_without_a_valid_token(
    client: TestClient, headers: dict[str, str]
) -> None:
    _refused(client.get("/api/v1/platform/access", headers=headers))


@pytest.mark.usefixtures("access")
def test_the_caddy_probe_accepts_a_valid_token(client: TestClient) -> None:
    response = client.get("/api/v1/platform/access", headers={HEADER: token()})
    assert response.status_code == 204


@pytest.mark.usefixtures("access", "platform_bound_to_test_database")
def test_a_good_password_without_a_token_is_refused(client: TestClient) -> None:
    account = create_platform_account("administrator")
    credentials = {"email": account.email, "password": PLATFORM_PASSWORD}

    _refused(client.post("/api/v1/platform/auth/login", json=credentials))

    response = client.post(
        "/api/v1/platform/auth/login", json=credentials, headers={HEADER: token()}
    )
    assert response.status_code == 200, response.text
    bearer = {"Authorization": f"Bearer {response.json()['access_token']}"}

    # Le jeton de l'administration ne remplace pas celui de Cloudflare.
    _refused(client.get("/api/v1/platform/auth/me", headers=bearer))
    me = client.get("/api/v1/platform/auth/me", headers={**bearer, HEADER: token()})
    assert me.status_code == 200, me.text


@pytest.mark.usefixtures("access")
@pytest.mark.parametrize(
    "path", ["/api/v1/platform/companies", "/api/v1/platform/system/workers", "/api/v1/platform"]
)
def test_every_platform_path_is_gated(client: TestClient, path: str) -> None:
    _refused(client.get(path))


@pytest.mark.usefixtures("access")
def test_merchant_routes_do_not_change(client: TestClient) -> None:
    assert client.get("/api/v1/health").status_code == 200
    # `/api/v1/platformes` n'est pas l'administration : le préfixe est un segment entier.
    assert client.get("/api/v1/platformes").status_code == 404
    login = client.post("/api/v1/auth/login", json={"identifier": "x", "password": "y"})
    assert login.status_code != 403


def test_without_configuration_nothing_is_checked(client: TestClient) -> None:
    _clear()
    assert client.get("/api/v1/platform/access").status_code == 204
