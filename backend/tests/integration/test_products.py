"""Module Products — fiche, contraintes de saisie, recherche, façade.

Les invariants de tarification ont leur propre suite : `test_product_prices.py`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.products import service as products_service
from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant

pytestmark = pytest.mark.integration


def _marker() -> str:
    """Suffixe unique : la base de test est partagée par toute la session."""
    return uuid4().hex[:8]


def create_product(client: TestClient, token: str, **overrides: Any) -> dict[str, Any]:
    marker = _marker()
    payload: dict[str, Any] = {
        "sku": f"SKU-{marker}",
        "name": f"Produit {marker}",
        "unit_price": "1500.00",
    }
    payload.update(overrides)
    response = client.post("/api/v1/products", headers=auth_headers(token), json=payload)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def test_a_product_is_created_with_its_first_price(
    api_client: TestClient, alpha_token: str
) -> None:
    """Un produit naît tarifé : `unit_price` est obligatoire (ADR 0011)."""
    product = create_product(api_client, alpha_token, unit_price="2500.00", cost_price="1800.0000")

    assert product["unit_price"] == "2500.00"
    assert product["cost_price"] == "1800.0000"
    assert product["is_active"] is True
    assert product["unit"] == "piece"


def test_a_product_cannot_be_created_without_a_price(
    api_client: TestClient, alpha_token: str
) -> None:
    """Sans prix, le produit ne serait pas vendable : le schéma refuse."""
    marker = _marker()
    response = api_client.post(
        "/api/v1/products",
        headers=auth_headers(alpha_token),
        json={"sku": f"SKU-{marker}", "name": f"Produit {marker}"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_amounts_travel_as_strings_never_as_floats(
    api_client: TestClient, alpha_token: str
) -> None:
    """Règle absolue du projet : jamais de flottant sur une donnée financière."""
    product = create_product(api_client, alpha_token, unit_price="1234.50")

    body = api_client.get(
        f"/api/v1/products/{product['id']}", headers=auth_headers(alpha_token)
    ).json()
    assert isinstance(body["unit_price"], str)
    assert isinstance(body["default_tax_rate"], str)


def test_a_float_amount_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """Un JSON contenant un flottant est rejeté, pas arrondi en silence."""
    marker = _marker()
    response = api_client.post(
        "/api/v1/products",
        headers=auth_headers(alpha_token),
        json={"sku": f"SKU-{marker}", "name": f"Produit {marker}", "unit_price": 1500.5},
    )
    assert response.status_code == 422


def test_the_sku_is_unique_per_company(api_client: TestClient, alpha_token: str) -> None:
    """`products_sku_uq` : deux produits d'une même entreprise n'ont pas le même SKU."""
    product = create_product(api_client, alpha_token)

    duplicate = api_client.post(
        "/api/v1/products",
        headers=auth_headers(alpha_token),
        json={"sku": product["sku"], "name": "Doublon", "unit_price": "100.00"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "product_sku_taken"


def test_the_same_sku_is_free_in_another_company(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """L'unicité est **par entreprise** : Beta peut utiliser le SKU d'Alpha."""
    product = create_product(api_client, alpha_token)

    response = api_client.post(
        "/api/v1/products",
        headers=auth_headers(beta_token),
        json={
            "sku": product["sku"],
            "name": "Même référence, autre entreprise",
            "unit_price": "100.00",
        },
    )
    assert response.status_code == 201


def test_the_sku_is_upper_cased(api_client: TestClient, alpha_token: str) -> None:
    """« riz-25 » et « RIZ-25 » désigneraient sinon deux produits pour un article."""
    marker = _marker()
    product = create_product(api_client, alpha_token, sku=f"riz-{marker}")
    assert product["sku"] == f"RIZ-{marker}".upper()


def test_an_unknown_unit_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """`unit` est limité aux valeurs du CHECK : les 6 du § 8.3, plus sac et bouteille (0015)."""
    marker = _marker()
    response = api_client.post(
        "/api/v1/products",
        headers=auth_headers(alpha_token),
        json={
            "sku": f"SKU-{marker}",
            "name": "Unité inventée",
            "unit": "tonneau",
            "unit_price": "100.00",
        },
    )
    assert response.status_code == 422


def test_a_tax_rate_of_one_or_more_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """`CHECK (default_tax_rate >= 0 AND default_tax_rate < 1)` : un taux, pas un pourcentage."""
    marker = _marker()
    response = api_client.post(
        "/api/v1/products",
        headers=auth_headers(alpha_token),
        json={
            "sku": f"SKU-{marker}",
            "name": "Taxe impossible",
            "default_tax_rate": "18",
            "unit_price": "100.00",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_product_can_be_searched_by_name_or_scanned_by_barcode(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le nom par approximation, le code-barres par égalité stricte."""
    marker = _marker()
    product = create_product(
        api_client, alpha_token, name=f"Sucre en poudre {marker}", barcode=f"340000{marker}"
    )

    by_name = api_client.get(
        "/api/v1/products?search=Sucre en poudre", headers=auth_headers(alpha_token)
    )
    assert product["id"] in {item["id"] for item in by_name.json()["items"]}

    by_barcode = api_client.get(
        f"/api/v1/products?search=340000{marker}", headers=auth_headers(alpha_token)
    )
    assert [item["id"] for item in by_barcode.json()["items"]] == [product["id"]]


def test_products_can_be_filtered_by_category(api_client: TestClient, alpha_token: str) -> None:
    """Le rattachement à une catégorie est vérifié, et filtrable."""
    category = api_client.post(
        "/api/v1/categories", headers=auth_headers(alpha_token), json={"name": f"Rayon {_marker()}"}
    ).json()
    product = create_product(api_client, alpha_token, category_id=category["id"])

    response = api_client.get(
        f"/api/v1/products?category_id={category['id']}", headers=auth_headers(alpha_token)
    )
    assert [item["id"] for item in response.json()["items"]] == [product["id"]]


def test_a_category_from_another_company_is_not_found(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """Le `category_id` du corps suit la même règle que le chemin : 404."""
    foreign = api_client.post(
        "/api/v1/categories", headers=auth_headers(beta_token), json={"name": f"Beta {_marker()}"}
    ).json()

    marker = _marker()
    response = api_client.post(
        "/api/v1/products",
        headers=auth_headers(alpha_token),
        json={
            "sku": f"SKU-{marker}",
            "name": "Tentative",
            "category_id": foreign["id"],
            "unit_price": "100.00",
        },
    )
    assert response.status_code == 404


def test_a_deleted_product_disappears_and_is_audited(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Suppression **logique** et audit critique : un produit vendu ne s'efface pas."""
    product = create_product(api_client, alpha_token)

    deleted = api_client.delete(
        f"/api/v1/products/{product['id']}", headers=auth_headers(alpha_token)
    )
    assert deleted.status_code == 200
    assert deleted.json()["is_active"] is False

    assert (
        api_client.get(
            f"/api/v1/products/{product['id']}", headers=auth_headers(alpha_token)
        ).status_code
        == 404
    )
    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs "
        "WHERE entity_table = 'products' AND entity_id = :id AND action = 'delete'",
        {"id": product["id"]},
    )
    assert audited == 1


def test_a_category_holding_active_products_cannot_be_deleted(
    api_client: TestClient, alpha_token: str
) -> None:
    """La garde en base tient, bien que `Categories` ne connaisse pas `Products`."""
    category = api_client.post(
        "/api/v1/categories", headers=auth_headers(alpha_token), json={"name": f"Plein {_marker()}"}
    ).json()
    product = create_product(api_client, alpha_token, category_id=category["id"])

    refused = api_client.delete(
        f"/api/v1/categories/{category['id']}", headers=auth_headers(alpha_token)
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "category_not_empty"

    # Le produit retiré, la catégorie redevient supprimable.
    api_client.delete(f"/api/v1/products/{product['id']}", headers=auth_headers(alpha_token))
    assert (
        api_client.delete(
            f"/api/v1/categories/{category['id']}", headers=auth_headers(alpha_token)
        ).status_code
        == 200
    )


def test_the_facade_answers_what_sales_and_inventory_will_ask(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """`get_current_price`, `get_tax_rate`, `is_stock_tracked`, `assert_sellable`.

    Ces quatre fonctions sont le contrat que Sales et Inventory consommeront en
    phases 04 et 05 : elles sont testées comme telles, sans passer par l'API.
    """
    product = create_product(
        api_client,
        alpha_token,
        unit_price="3000.00",
        cost_price="2100.0000",
        default_tax_rate="0.18",
        is_stock_tracked=False,
    )
    product_id = product["id"]
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)

    with tenant_transaction(ctx, session_factory=session_factory) as session:
        price = products_service.get_current_price(session, ctx, product_id)
        assert price.unit_price == Decimal("3000.00")
        assert price.cost_price == Decimal("2100.0000")
        assert products_service.get_tax_rate(session, ctx, product_id) == Decimal("0.1800")
        assert products_service.is_stock_tracked(session, ctx, product_id) is False
        assert products_service.assert_sellable(session, ctx, product_id).unit_price == Decimal(
            "3000.00"
        )


def test_an_inactive_product_is_not_sellable(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """`assert_sellable` refuse un produit désactivé, avec un code métier nommé."""
    product = create_product(api_client, alpha_token)
    api_client.patch(
        f"/api/v1/products/{product['id']}",
        headers=auth_headers(alpha_token),
        json={"is_active": False},
    )

    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)
    with (
        pytest.raises(products_service.ProductInactiveError),
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        products_service.assert_sellable(session, ctx, product["id"])
