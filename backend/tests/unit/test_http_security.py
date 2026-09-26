"""Garde-fous HTTP de l'API (ADR 0042) : en-têtes, taille des corps, CORS."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings


def test_security_headers_are_set_on_every_response(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_security_headers_are_set_on_errors_too(client: TestClient) -> None:
    response = client.get("/api/v1/route-inexistante")
    assert response.status_code == 404
    assert response.headers["x-frame-options"] == "DENY"


def test_docs_are_not_locked_by_the_api_csp(client: TestClient) -> None:
    # Swagger UI charge ses ressources depuis un CDN : la CSP fermée la casserait.
    response = client.get("/api/v1/docs")
    assert response.status_code == 200
    assert "content-security-policy" not in response.headers


def test_declared_oversized_body_is_refused_with_413(client: TestClient) -> None:
    limit = get_settings().max_body_bytes
    response = client.post(
        "/api/v1/auth/login",
        content=b"x" * (limit + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_streamed_oversized_body_is_refused_with_413(client: TestClient) -> None:
    limit = get_settings().max_body_bytes

    def chunks():  # type: ignore[no-untyped-def]
        for _ in range(limit // 1024 + 2):
            yield b"x" * 1024

    # Pas de Content-Length : la taille n'est découverte qu'en lisant le flux.
    response = client.post(
        "/api/v1/auth/login", content=chunks(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413


def test_cors_rejects_an_unknown_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "origin": "https://pirate.example.com",
            "access-control-request-method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers
