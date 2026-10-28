"""Version minimale du front (prompt 29, P2, ADR 0102).

Un front trop ancien se reconnaît à `X-CoGes-Front` ; l'API lui répond 426 `front_outdated`,
qui déclenche sa mise à jour à un moment sûr. Sans réglage, ou sans en-tête (fronts d'avant
ce lot), rien n'est refusé.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def minimum(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("COGES_MIN_FRONT_VERSION", "1.4.0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _health(client: TestClient, version: str | None) -> int:
    headers = {} if version is None else {"X-CoGes-Front": version}
    return client.get("/api/v1/health", headers=headers).status_code


def test_no_minimum_refuses_nothing() -> None:
    with TestClient(app) as client:
        assert _health(client, "0.0.1") == 200


@pytest.mark.usefixtures("minimum")
def test_an_older_front_is_told_to_update() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"X-CoGes-Front": "1.3.9"})
    assert response.status_code == 426
    assert response.json()["error"]["code"] == "front_outdated"
    assert response.json()["error"]["details"] == {"minimum": "1.4.0", "front": "1.3.9"}


@pytest.mark.usefixtures("minimum")
@pytest.mark.parametrize("version", ["1.4.0", "1.4.1", "1.10.0", "2.0.0"])
def test_the_minimum_and_newer_pass(version: str) -> None:
    with TestClient(app) as client:
        assert _health(client, version) == 200


@pytest.mark.usefixtures("minimum")
@pytest.mark.parametrize("version", [None, "", "dev", "abc"])
def test_a_missing_or_unreadable_version_is_not_refused(version: str | None) -> None:
    """Un front d'avant ce lot n'envoie rien : le refuser le bloquerait sans recours."""
    with TestClient(app) as client:
        assert _health(client, version) == 200


@pytest.mark.usefixtures("minimum")
def test_outside_the_api_nothing_is_checked() -> None:
    with TestClient(app) as client:
        response = client.get("/hors-api", headers={"X-CoGes-Front": "0.1.0"})
    assert response.status_code == 404
