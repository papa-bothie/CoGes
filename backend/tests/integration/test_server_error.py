"""Toute erreur imprévue sort en 500 au format stable, sans détail interne (ADR 0085).

Le commerçant voit « un souci de notre côté » et une référence d'incident qu'il peut lire
au téléphone ; la même référence est dans l'en-tête, dans le journal et dans Sentry.
Jamais de trace, de chemin de fichier, de requête SQL ni de donnée d'une entreprise.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.integration

SECRET = "/srv/coges/app/modules/sales/service.py company 7c1f… SELECT * FROM sales"


@pytest.fixture
def broken_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def explode() -> object:
        raise RuntimeError(SECRET)

    monkeypatch.setattr("app.main.readiness", explode)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_an_unexpected_error_is_a_stable_500(broken_client: TestClient) -> None:
    response = broken_client.get("/api/v1/health/ready")

    assert response.status_code == 500
    body = response.json()
    request_id = response.headers["x-request-id"]
    assert body == {
        "error": {
            "code": "server_error",
            "message": "Un souci de notre côté. Vos données sont en sécurité. "
            "Réessayez dans un instant.",
            "details": {},
            "request_id": request_id,
        }
    }
    for leak in ("/srv/", "service.py", "SELECT", "company", "Traceback", "RuntimeError"):
        assert leak not in response.text


def test_the_reference_is_in_the_log(broken_client: TestClient) -> None:
    # Handler posé sur le logger lui-même : la configuration des journaux de l'application
    # peut couper la propagation vers la racine, où `caplog` écoute.
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Collect(level=logging.ERROR)
    access = logging.getLogger("coges.access")
    access.addHandler(handler)
    try:
        response = broken_client.get("/api/v1/health/ready")
    finally:
        access.removeHandler(handler)
    request_id = response.headers["x-request-id"]
    mine = [r for r in records if getattr(r, "request_id", None) == request_id]
    assert mine, "aucune ligne de journal ne porte la référence d'incident"
    assert any(r.exc_info for r in mine), "la trace doit rester dans le journal"


def test_a_client_supplied_request_id_is_kept_only_when_well_formed(
    broken_client: TestClient,
) -> None:
    kept = broken_client.get(
        "/api/v1/health/ready", headers={"x-request-id": "ab12cd34-5678-90ef-aa00-123456789abc"}
    )
    assert kept.headers["x-request-id"] == "ab12cd34-5678-90ef-aa00-123456789abc"

    forged = broken_client.get(
        "/api/v1/health/ready", headers={"x-request-id": "x\r\nSet-Cookie: pirate=1"}
    )
    assert forged.headers["x-request-id"] != "x\r\nSet-Cookie: pirate=1"
    assert forged.json()["error"]["request_id"] == forged.headers["x-request-id"]
