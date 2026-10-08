"""Références et codes-barres générés (ADR 0066).

Un article créé sans référence reçoit `ART-0001`, `ART-0002`… par entreprise ; sans code
scanné, un EAN-13 interne (préfixe 2, clé de contrôle valide), unique dans l'entreprise.
Une entreprise neuve par test : le compteur se lit depuis zéro.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.products import service as products_service
from app.modules.products.schemas import ProductCreate
from tests.conftest import DemoCompany, _create_demo_company, auth_headers, login_token

pytestmark = pytest.mark.integration

PRODUCTS = "/api/v1/products"


def ean13_is_valid(code: str) -> bool:
    """Clé de contrôle GS1 : poids 1 et 3 en alternance sur les douze premiers chiffres."""
    if len(code) != 13 or not code.isdigit():
        return False
    total = sum(int(digit) * (3 if index % 2 else 1) for index, digit in enumerate(code[:12]))
    return (10 - total % 10) % 10 == int(code[12])


@pytest.fixture
def shop(app_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"codes-{uuid4().hex[:8]}")


@pytest.fixture
def token(api_client: TestClient, shop: DemoCompany) -> str:
    return login_token(api_client, shop)


def _create(client: TestClient, token: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": f"Article {uuid4().hex[:6]}", "unit_price": "1000"}
    payload.update(fields)
    response = client.post(PRODUCTS, headers=auth_headers(token), json=payload)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def test_a_product_without_sku_gets_the_next_art_code(api_client: TestClient, token: str) -> None:
    first = _create(api_client, token)
    second = _create(api_client, token)
    assert (first["sku"], second["sku"]) == ("ART-0001", "ART-0002")


def test_the_counter_follows_codes_typed_by_hand(api_client: TestClient, token: str) -> None:
    _create(api_client, token, sku="ART-0041")
    _create(api_client, token, sku="RIZ-25")
    assert _create(api_client, token)["sku"] == "ART-0042"


def test_a_product_without_barcode_gets_an_internal_ean13(
    api_client: TestClient, token: str
) -> None:
    first = _create(api_client, token)
    second = _create(api_client, token)
    for product in (first, second):
        assert product["barcode"].startswith("2")
        assert ean13_is_valid(product["barcode"]), product["barcode"]
    assert first["barcode"] != second["barcode"]


def test_a_scanned_barcode_wins(api_client: TestClient, token: str) -> None:
    product = _create(api_client, token, barcode="6111245017801")
    assert product["barcode"] == "6111245017801"


def test_generated_codes_are_per_company(
    api_client: TestClient, token: str, app_bound_to_test_database: None
) -> None:
    other = _create_demo_company(f"codes-{uuid4().hex[:8]}")
    first = _create(api_client, token)
    second = _create(api_client, token)
    theirs = _create(api_client, login_token(api_client, other))
    assert second["sku"] == "ART-0002"
    assert theirs["sku"] == "ART-0001"
    # Chaque entreprise a son compteur : le même EAN interne existe des deux côtés.
    assert theirs["barcode"] == first["barcode"]


@pytest.mark.parametrize("unit", ["sac", "bouteille"])
def test_bags_and_bottles_are_units(api_client: TestClient, token: str, unit: str) -> None:
    assert _create(api_client, token, unit=unit)["unit"] == unit


def test_two_products_created_at_once_get_different_codes(
    shop: DemoCompany, concurrent_session_factory: sessionmaker[Any]
) -> None:
    """La seconde création calcule le même numéro, bute sur l'index unique, recommence."""
    ctx = TenantContext(user_id=shop.manager_id, company_id=shop.company_id)

    def create() -> tuple[str, str | None]:
        with tenant_transaction(ctx, session_factory=concurrent_session_factory) as session:
            product, _ = products_service.create_product(
                session, ctx, ProductCreate(name="Concurrent", unit_price=Decimal(500))
            )
            return product.sku, product.barcode

    with ThreadPoolExecutor(max_workers=1) as pool:
        with tenant_transaction(ctx, session_factory=concurrent_session_factory) as session:
            held, _ = products_service.create_product(
                session, ctx, ProductCreate(name="Tenu", unit_price=Decimal(500))
            )
            # La seconde création part pendant que la première n'est pas validée : elle
            # calcule le même numéro et attend l'index unique.
            future = pool.submit(create)
        sku, barcode = future.result(timeout=30)

    assert held.sku == "ART-0001"
    assert sku == "ART-0002"
    assert barcode is not None and barcode != held.barcode
    assert ean13_is_valid(barcode)
