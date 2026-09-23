"""Scénario de bout en bout du référentiel, tel qu'une PME l'enchaîne.

Catégorie → produit tarifé → changement de prix → historique → tiers. Ce test ne
vérifie pas une règle en particulier : il vérifie que les quatre modules de la
bande B **fonctionnent ensemble**, avec les permissions, la pagination et les
montants sous forme de chaînes.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant

pytestmark = pytest.mark.integration


def test_the_whole_referential_chain(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Le parcours complet : classer, tarifer, retarifer, relire, et tracer."""
    headers = auth_headers(alpha_token)
    marker = uuid4().hex[:6]

    # 1. Une catégorie, puis une sous-catégorie.
    rayon = api_client.post(
        "/api/v1/categories", headers=headers, json={"name": f"Épicerie {marker}"}
    ).json()
    sous_rayon = api_client.post(
        "/api/v1/categories",
        headers=headers,
        json={"name": f"Riz {marker}", "parent_id": rayon["id"]},
    ).json()
    assert sous_rayon["parent_id"] == rayon["id"]

    # 2. Un produit rangé dans la sous-catégorie, tarifé dès la création.
    product = api_client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"RIZ-25-{marker}",
            "name": f"Riz parfumé 25 kg {marker}",
            "unit": "kg",
            "category_id": sous_rayon["id"],
            "default_tax_rate": "0.18",
            "reorder_point": "50",
            "unit_price": "18500.00",
            "cost_price": "15200.0000",
        },
    ).json()
    assert product["unit_price"] == "18500.00"
    assert product["cost_price"] == "15200.0000"
    assert product["default_tax_rate"] == "0.1800"

    # 3. Le prix augmente. L'ancien intervalle se ferme au même instant.
    new_price = api_client.post(
        f"/api/v1/products/{product['id']}/prices",
        headers=headers,
        json={"unit_price": "19750.00", "cost_price": "16100.0000"},
    )
    assert new_price.status_code == 201

    # 4. L'historique porte les deux intervalles, un seul ouvert, sans trou.
    history = api_client.get(f"/api/v1/products/{product['id']}/prices", headers=headers).json()
    assert history["total"] == 2
    current, previous = history["items"]
    assert (current["unit_price"], current["valid_to"]) == ("19750.00", None)
    assert previous["unit_price"] == "18500.00"
    assert previous["valid_to"] == current["valid_from"]

    # 5. La fiche affiche le prix en vigueur, jamais un prix figé sur le produit.
    refreshed = api_client.get(f"/api/v1/products/{product['id']}", headers=headers).json()
    assert refreshed["unit_price"] == "19750.00"

    # 6. Le changement de prix est tracé dans l'audit critique.
    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs WHERE entity_table = 'product_prices' "
        "AND action = 'update' AND entity_id = :id",
        {"id": current["id"]},
    )
    assert audited == 1

    # 7. Un client et un fournisseur, avec leurs codes attribués par le serveur.
    customer = api_client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": f"Boutique Sandaga {marker}", "credit_limit": "250000"},
    ).json()
    supplier = api_client.post(
        "/api/v1/suppliers",
        headers=headers,
        json={"name": f"Grossiste Thiaroye {marker}", "payment_terms_days": 30},
    ).json()
    assert customer["code"].startswith("CLI-")
    assert supplier["code"].startswith("FRN-")
    assert customer["credit_limit"] == "250000.00"

    # 8. La catégorie qui porte le produit ne peut pas être supprimée.
    refused = api_client.delete(f"/api/v1/categories/{sous_rayon['id']}", headers=headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "category_not_empty"

    # 9. Tout cela est paginé et filtrable.
    listing = api_client.get(
        f"/api/v1/products?category_id={sous_rayon['id']}&page_size=10", headers=headers
    ).json()
    assert listing["page_size"] == 10
    assert [item["id"] for item in listing["items"]] == [product["id"]]
