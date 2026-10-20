"""L'administration voit A **et** B, dans les colonnes permises seulement (ADR 0089).

L'inverse de `tests/tenancy` : on ne prouve pas qu'une entreprise ne voit pas l'autre,
on prouve que l'administration les voit toutes les deux — et que le résumé de l'une
ne contient jamais rien de l'autre, ni aucune donnée commerciale de l'une ou l'autre.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import TEST_BASE_URL, DemoCompany, _create_demo_company, auth_headers
from tests.integration.platform_harness import create_platform_account, platform_login

pytestmark = pytest.mark.tenancy

SUMMARY_KEYS = {"id", "name", "slug", "status", "created_at", "user_count", "last_activity_at"}
USER_KEYS = {"id", "full_name", "roles", "is_active", "last_login_at"}


@pytest.fixture(scope="module")
def client(platform_bound_to_test_database: None) -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def pair(platform_bound_to_test_database: None) -> tuple[DemoCompany, DemoCompany]:
    marker = uuid4().hex[:6]
    return (
        _create_demo_company(f"plateforme-a-{marker}"),
        _create_demo_company(f"plateforme-b-{marker}"),
    )


@pytest.fixture(scope="module")
def token(client: TestClient) -> str:
    return platform_login(client, create_platform_account("support"))


def _markers(company: DemoCompany) -> list[str]:
    return [company.slug, str(company.company_id), str(company.manager_id), company.email]


def test_both_companies_are_visible(
    client: TestClient, token: str, pair: tuple[DemoCompany, DemoCompany]
) -> None:
    a, b = pair
    marker = a.slug.rsplit("-", 1)[1]
    response = client.get(
        "/api/v1/platform/companies", headers=auth_headers(token), params={"search": marker}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["slug"] for item in items} == {a.slug, b.slug}
    for item in items:
        assert set(item) == SUMMARY_KEYS


@pytest.mark.parametrize("which", [0, 1])
def test_the_detail_of_one_holds_nothing_of_the_other(
    client: TestClient, token: str, pair: tuple[DemoCompany, DemoCompany], which: int
) -> None:
    mine, other = pair[which], pair[1 - which]
    response = client.get(
        f"/api/v1/platform/companies/{mine.company_id}", headers=auth_headers(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == SUMMARY_KEYS | {"users"}
    assert all(set(user) == USER_KEYS for user in body["users"])
    assert body["slug"] == mine.slug
    assert {user["id"] for user in body["users"]} == {str(mine.manager_id)}
    serialized = json.dumps(body)
    leaked = [marker for marker in _markers(other) if marker in serialized]
    assert leaked == []
    # Ni e-mail ni téléphone ne sortent, même ceux de l'entreprise elle-même.
    assert mine.email not in serialized


def test_searching_one_never_returns_the_other(
    client: TestClient, token: str, pair: tuple[DemoCompany, DemoCompany]
) -> None:
    a, b = pair
    response = client.get(
        "/api/v1/platform/companies", headers=auth_headers(token), params={"search": a.slug}
    )
    assert [item["slug"] for item in response.json()["items"]] == [a.slug]
    assert b.slug not in response.text
