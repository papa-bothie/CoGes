"""`?search=%00` : 200 et non 500 (P2.23, ADR 0088)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("path", ["/api/v1/customers", "/api/v1/suppliers", "/api/v1/products"])
def test_a_nul_in_the_search_is_ignored(
    api_client: TestClient, alpha_token: str, path: str
) -> None:
    response = api_client.get(path, headers=auth_headers(alpha_token), params={"search": "ri\x00z"})
    assert response.status_code == 200, response.text
