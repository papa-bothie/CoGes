"""Taux de TVA par défaut de l'entreprise (ADR 0066, complément du 2026-10-08).

Le formulaire court ne demande plus la TVA : un article créé sans taux prend celui des
réglages de l'entreprise (`settings.default_tax_rate`), 0 s'il n'y en a pas. Un taux
envoyé, même 0, n'est jamais remplacé.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DemoCompany, _create_demo_company, auth_headers, login_token

pytestmark = pytest.mark.integration


@pytest.fixture
def token(api_client: TestClient, app_bound_to_test_database: None) -> str:
    shop: DemoCompany = _create_demo_company(f"tva-{uuid4().hex[:8]}")
    return login_token(api_client, shop)


def _set(client: TestClient, token: str, settings: dict[str, Any]) -> Any:
    return client.patch(
        "/api/v1/companies/me", headers=auth_headers(token), json={"settings": settings}
    )


def _product(client: TestClient, token: str, **fields: Any) -> dict[str, Any]:
    payload = {"name": f"Article {uuid4().hex[:6]}", "unit_price": "1000", **fields}
    response = client.post("/api/v1/products", headers=auth_headers(token), json=payload)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def test_without_setting_a_product_is_not_taxed(api_client: TestClient, token: str) -> None:
    assert _product(api_client, token)["default_tax_rate"] == "0.0000"


def test_a_product_without_rate_takes_the_company_rate(api_client: TestClient, token: str) -> None:
    assert _set(api_client, token, {"default_tax_rate": "0.18"}).status_code == 200
    assert _product(api_client, token)["default_tax_rate"] == "0.1800"
    assert _product(api_client, token, default_tax_rate=None)["default_tax_rate"] == "0.1800"


def test_a_rate_sent_is_kept_even_zero(api_client: TestClient, token: str) -> None:
    _set(api_client, token, {"default_tax_rate": "0.18"})
    assert _product(api_client, token, default_tax_rate="0")["default_tax_rate"] == "0.0000"


@pytest.mark.parametrize("rate", ["1", "-0.1", "dix", 0.18, "0.123456"])
def test_an_impossible_rate_is_refused(api_client: TestClient, token: str, rate: Any) -> None:
    assert _set(api_client, token, {"default_tax_rate": rate}).status_code == 422
