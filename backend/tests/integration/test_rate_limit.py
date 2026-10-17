"""Limitation de débit par IP et par entreprise (décision 16, ADR 0042).

La suite la coupe par défaut (`tests/__init__.py`) ; ces tests la rallument en
substituant des réglages bas, puis vident leurs compteurs Redis.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import cache, rate_limit
from app.core.config import get_settings
from tests.conftest import DemoCompany, auth_headers


@pytest.fixture
def low_limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if cache.get_client() is None:
        pytest.skip("Redis requis")
    # Une IP de test propre à ce test : aucun compteur partagé avec un autre.
    ip = f"10.{uuid4().int % 250}.{uuid4().int % 250}.{uuid4().int % 250}"
    low = get_settings().model_copy(
        update={
            "rate_limit_ip_per_minute": 5,
            "rate_limit_login_per_minute": 2,
            "rate_limit_tenant_per_minute": 3,
            "trust_proxy_headers": True,
        }
    )
    monkeypatch.setattr(rate_limit, "get_settings", lambda: low)
    # Horloge figée en début de fenêtre : le cas ne peut pas chevaucher deux minutes.
    monkeypatch.setattr(rate_limit, "_clock", lambda: 1_800_000_000.0 - 1_800_000_000 % 60 + 1)
    monkeypatch.setattr("app.core.deps.get_settings", lambda: low)
    monkeypatch.setenv("TEST_CLIENT_IP", ip)
    yield


def _ip() -> dict[str, str]:
    import os

    return {"x-forwarded-for": os.environ["TEST_CLIENT_IP"]}


def test_ip_limit_returns_429_with_retry_after(low_limits: None, client: TestClient) -> None:
    statuses = [client.get("/api/v1/health", headers=_ip()).status_code for _ in range(7)]
    assert statuses[:5] == [200] * 5
    assert statuses[5:] == [429, 429]
    response = client.get("/api/v1/health", headers=_ip())
    assert response.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(response.headers["retry-after"]) <= 60


def test_a_forged_forwarded_for_does_not_escape_the_ip_limit(
    low_limits: None, client: TestClient
) -> None:
    """Le client invente une adresse à gauche ; Caddy ajoute la vraie à droite (ADR 0083).

    Chaque requête porte une fausse adresse différente : si l'API lisait la gauche,
    chacune tomberait dans un compteur neuf et la limite ne jouerait jamais.
    """
    import os

    real = os.environ["TEST_CLIENT_IP"]
    statuses = [
        client.get(
            "/api/v1/health", headers={"x-forwarded-for": f"198.51.100.{n}, {real}"}
        ).status_code
        for n in range(7)
    ]
    assert statuses[:5] == [200] * 5
    assert statuses[5:] == [429, 429]


def test_login_has_a_stricter_bucket(low_limits: None, client: TestClient) -> None:
    body = {"company_slug": "inconnue", "email": "x@example.com", "password": "mauvais-mot"}
    statuses = [
        client.post("/api/v1/auth/login", json=body, headers=_ip()).status_code for _ in range(3)
    ]
    assert statuses[2] == 429


def test_tenant_limit_counts_per_company(
    low_limits: None,
    api_client: TestClient,
    company_alpha: DemoCompany,
    alpha_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Le compteur par IP est neutralisé pour isoler celui de l'entreprise.
    monkeypatch.setattr(rate_limit, "hit_ip", lambda ip: None)
    client = cache.get_client()
    assert client is not None
    for stale in client.scan_iter(f"{cache.NAMESPACE}:rl:tenant:{company_alpha.company_id}:*"):
        client.delete(stale)

    headers = auth_headers(alpha_token)
    statuses = [api_client.get("/api/v1/products", headers=headers).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]


def test_redis_outage_lets_requests_through(
    low_limits: None, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache, "get_client", lambda: None)
    statuses = {client.get("/api/v1/health", headers=_ip()).status_code for _ in range(10)}
    assert statuses == {200}
