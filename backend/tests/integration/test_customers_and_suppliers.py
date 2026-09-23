"""Modules Customers et Suppliers — codes attribués, plafonds, suppression auditée.

Les deux modules suivent le même gabarit et partagent la mécanique de numérotation
(`app/core/codes.py`) : ils sont testés côte à côte pour que toute divergence entre
les deux se voie.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant

pytestmark = pytest.mark.integration

CODE_FORMAT = re.compile(r"^(CLI|FRN)-\d{4,}$")


def _marker() -> str:
    return uuid4().hex[:8]


def _create(client: TestClient, token: str, resource: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": f"Tiers {_marker()}"}
    payload.update(overrides)
    response = client.post(f"/api/v1/{resource}", headers=auth_headers(token), json=payload)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


@pytest.mark.parametrize(("resource", "prefix"), [("customers", "CLI"), ("suppliers", "FRN")])
def test_a_code_is_generated_and_follows_the_convention(
    api_client: TestClient, alpha_token: str, resource: str, prefix: str
) -> None:
    """Sans code fourni, le serveur attribue `CLI-0001` / `FRN-0001`, puis incrémente."""
    first = _create(api_client, alpha_token, resource)
    second = _create(api_client, alpha_token, resource)

    assert CODE_FORMAT.match(first["code"]), first["code"]
    assert first["code"].startswith(prefix)
    assert first["code"] != second["code"]
    assert int(second["code"].split("-")[1]) == int(first["code"].split("-")[1]) + 1


@pytest.mark.parametrize("resource", ["customers", "suppliers"])
def test_a_chosen_code_is_kept_as_is(
    api_client: TestClient, alpha_token: str, resource: str
) -> None:
    """Le code reste modifiable : celui de l'appelant prime sur la numérotation."""
    code = f"MAISON-{_marker()}".upper()
    created = _create(api_client, alpha_token, resource, code=code)
    assert created["code"] == code


@pytest.mark.parametrize("resource", ["customers", "suppliers"])
def test_a_code_is_unique_per_company(
    api_client: TestClient, alpha_token: str, beta_token: str, resource: str
) -> None:
    """Unicité **par entreprise** : le doublon est refusé chez soi, libre ailleurs."""
    code = f"DOUBLON-{_marker()}".upper()
    _create(api_client, alpha_token, resource, code=code)

    duplicate = api_client.post(
        f"/api/v1/{resource}",
        headers=auth_headers(alpha_token),
        json={"name": "Doublon", "code": code},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"].endswith("_code_taken")

    elsewhere = api_client.post(
        f"/api/v1/{resource}",
        headers=auth_headers(beta_token),
        json={"name": "Même code, autre entreprise", "code": code},
    )
    assert elsewhere.status_code == 201


@pytest.mark.parametrize("resource", ["customers", "suppliers"])
def test_the_code_is_upper_cased(api_client: TestClient, alpha_token: str, resource: str) -> None:
    """« cli-1 » et « CLI-1 » désigneraient sinon deux tiers pour un code affiché."""
    marker = _marker()
    created = _create(api_client, alpha_token, resource, code=f"tiers-{marker}")
    assert created["code"] == f"TIERS-{marker}".upper()


@pytest.mark.parametrize("resource", ["customers", "suppliers"])
def test_search_finds_by_name_or_by_exact_code(
    api_client: TestClient, alpha_token: str, resource: str
) -> None:
    """Nom par approximation, code par égalité stricte."""
    marker = _marker()
    created = _create(api_client, alpha_token, resource, name=f"Boutique Sandaga {marker}")

    by_name = api_client.get(
        f"/api/v1/{resource}?search=Boutique Sandaga", headers=auth_headers(alpha_token)
    )
    assert created["id"] in {item["id"] for item in by_name.json()["items"]}

    by_code = api_client.get(
        f"/api/v1/{resource}?search={created['code']}", headers=auth_headers(alpha_token)
    )
    assert [item["id"] for item in by_code.json()["items"]] == [created["id"]]


def test_a_customer_without_credit_limit_has_no_ceiling(
    api_client: TestClient, alpha_token: str
) -> None:
    """`null` = pas de plafond ; `0` = vente à crédit interdite. Les deux sont voulus."""
    unlimited = _create(api_client, alpha_token, "customers")
    assert unlimited["credit_limit"] is None

    forbidden = _create(api_client, alpha_token, "customers", credit_limit="0")
    assert forbidden["credit_limit"] == "0.00"


def test_a_negative_credit_limit_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """`CHECK (credit_limit >= 0)`, porté aussi par le schéma."""
    response = api_client.post(
        "/api/v1/customers",
        headers=auth_headers(alpha_token),
        json={"name": "Plafond négatif", "credit_limit": "-1"},
    )
    assert response.status_code == 422


def test_a_customer_email_is_validated(api_client: TestClient, alpha_token: str) -> None:
    """Une adresse mal formée est refusée à la saisie."""
    response = api_client.post(
        "/api/v1/customers",
        headers=auth_headers(alpha_token),
        json={"name": "Adresse douteuse", "email": "pas-une-adresse"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("payment_terms_days", [-1, 366])
def test_payment_terms_stay_within_a_year(
    api_client: TestClient, alpha_token: str, payment_terms_days: int
) -> None:
    """`CHECK (payment_terms_days BETWEEN 0 AND 365)`."""
    response = api_client.post(
        "/api/v1/suppliers",
        headers=auth_headers(alpha_token),
        json={"name": "Délai impossible", "payment_terms_days": payment_terms_days},
    )
    assert response.status_code == 422


def test_payment_terms_are_kept_when_valid(api_client: TestClient, alpha_token: str) -> None:
    supplier = _create(api_client, alpha_token, "suppliers", payment_terms_days=30)
    assert supplier["payment_terms_days"] == 30


@pytest.mark.parametrize(
    ("resource", "table"), [("customers", "customers"), ("suppliers", "suppliers")]
)
def test_a_deleted_party_disappears_and_is_audited(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    resource: str,
    table: str,
) -> None:
    """Suppression **logique** et audit critique : un tiers porte dettes et historique."""
    party = _create(api_client, alpha_token, resource)

    deleted = api_client.delete(
        f"/api/v1/{resource}/{party['id']}", headers=auth_headers(alpha_token)
    )
    assert deleted.status_code == 200
    assert (
        api_client.get(
            f"/api/v1/{resource}/{party['id']}", headers=auth_headers(alpha_token)
        ).status_code
        == 404
    )

    still_there = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        f"SELECT count(*) FROM {table} WHERE id = :id AND deleted_at IS NOT NULL",
        {"id": party["id"]},
    )
    assert still_there == 1

    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs "
        f"WHERE entity_table = '{table}' AND entity_id = :id AND action = 'delete'",
        {"id": party["id"]},
    )
    assert audited == 1


@pytest.mark.parametrize("resource", ["customers", "suppliers"])
def test_a_party_can_be_renamed_and_recoded(
    api_client: TestClient, alpha_token: str, resource: str
) -> None:
    """Modification partielle : seul ce qui est transmis change."""
    party = _create(api_client, alpha_token, resource)
    new_code = f"REF-{_marker()}".upper()

    response = api_client.patch(
        f"/api/v1/{resource}/{party['id']}",
        headers=auth_headers(alpha_token),
        json={"code": new_code},
    )
    assert response.status_code == 200
    assert response.json()["code"] == new_code
    assert response.json()["name"] == party["name"]
