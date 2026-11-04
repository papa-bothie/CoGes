"""Description d'un article (prompt 34, bloc D, ADR 0108)."""

from __future__ import annotations

import csv
import io
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, write_headers

pytestmark = pytest.mark.integration


def _create(client: TestClient, token: str, **body: Any) -> Any:
    payload = {"name": f"Article {uuid4().hex[:8]}", "unit_price": "1000", **body}
    return client.post("/api/v1/products", headers=auth_headers(token), json=payload)


def test_a_product_is_created_with_or_without_a_description(
    api_client: TestClient, alpha_token: str
) -> None:
    without = _create(api_client, alpha_token)
    assert without.status_code == 201, without.text
    assert without.json()["description"] is None

    multiline = "  Riz parfumé de la vallée.\nSac de 25 kg, cousu.  "
    created = _create(api_client, alpha_token, description=multiline)
    assert created.status_code == 201, created.text
    assert created.json()["description"] == "Riz parfumé de la vallée.\nSac de 25 kg, cousu."

    blank = _create(api_client, alpha_token, description="   ")
    assert blank.json()["description"] is None, "vide = rien"


def test_a_description_is_capped_at_500_characters(
    api_client: TestClient, alpha_token: str
) -> None:
    assert _create(api_client, alpha_token, description="x" * 500).status_code == 201
    refused = _create(api_client, alpha_token, description="x" * 501)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["details"]["fields"][0]["field"] == "description"


def test_the_new_product_with_stock_route_takes_a_description(
    api_client: TestClient, alpha_token: str
) -> None:
    created = api_client.post(
        "/api/v1/inventory/products",
        headers=write_headers(alpha_token),
        json={
            "name": f"Article {uuid4().hex[:8]}",
            "unit_price": "1000",
            "description": "Bouteille consignée",
        },
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["product"]["id"]
    read = api_client.get(f"/api/v1/products/{product_id}", headers=auth_headers(alpha_token))
    assert read.json()["description"] == "Bouteille consignée"


def test_a_description_is_changed_then_cleared(api_client: TestClient, alpha_token: str) -> None:
    product_id = _create(api_client, alpha_token, description="Ancienne").json()["id"]
    url = f"/api/v1/products/{product_id}"

    changed = api_client.patch(
        url, headers=auth_headers(alpha_token), json={"description": "Neuve"}
    )
    assert changed.json()["description"] == "Neuve"
    untouched = api_client.patch(url, headers=auth_headers(alpha_token), json={"name": "Autre nom"})
    assert untouched.json()["description"] == "Neuve", "un champ omis ne bouge pas"
    cleared = api_client.patch(url, headers=auth_headers(alpha_token), json={"description": ""})
    assert cleared.json()["description"] is None


def test_another_company_never_reads_the_description(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    product_id = _create(api_client, alpha_token, description="Secret d'Alpha").json()["id"]
    response = api_client.get(f"/api/v1/products/{product_id}", headers=auth_headers(beta_token))
    assert response.status_code == 404
    listed = api_client.get(
        "/api/v1/products", params={"page_size": 100}, headers=auth_headers(beta_token)
    )
    assert "Secret d'Alpha" not in listed.text


def test_the_description_goes_through_import_and_export(
    api_client: TestClient, alpha_token: str
) -> None:
    name = f"Importé {uuid4().hex[:8]}"
    content = f"Nom;Description;Prix de vente\n{name};Savon de Marseille;500\n".encode()
    imported = api_client.post(
        "/api/v1/imports/products",
        headers=write_headers(alpha_token),
        files={"file": ("import.csv", content, "application/octet-stream")},
    )
    assert imported.status_code == 201, imported.text

    old_file = f"Nom;Prix de vente\nSans description {uuid4().hex[:8]};500\n".encode()
    legacy = api_client.post(
        "/api/v1/imports/products",
        headers=write_headers(alpha_token),
        files={"file": ("import.csv", old_file, "application/octet-stream")},
    )
    assert legacy.status_code == 201, "la colonne est facultative"

    exported = api_client.get(
        "/api/v1/exports/referentials/products",
        params={"format": "csv"},
        headers=auth_headers(alpha_token),
    )
    assert exported.status_code == 200, exported.text
    rows = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][2] == "Description"
    row = next(row for row in rows if row[1] == name)
    assert row[2] == "Savon de Marseille"


# ------------------------------------------- deux articles de même nom (2026-11-04)


def _twins(client: TestClient, token: str) -> tuple[str, str, str]:
    """Deux « Huile » qui ne diffèrent que par leur description."""
    from tests.integration.test_sales_api import _make_product

    name = f"Huile {uuid4().hex[:6]}"
    small = _make_product(client, token, name=name, description="1 litre")
    large = _make_product(client, token, name=name, description="5 litres")
    return name, small, large


def test_the_search_finds_words_of_the_description(
    api_client: TestClient, alpha_token: str
) -> None:
    name, small, large = _twins(api_client, alpha_token)
    marker = name.split()[1]
    found = api_client.get(
        "/api/v1/products",
        params={"search": "5 litres", "page_size": 100},
        headers=auth_headers(alpha_token),
    ).json()["items"]
    ids = {item["id"] for item in found}
    assert large in ids and small not in ids
    # Et le stock, que l'écran Stock et la livraison interrogent.
    stock = api_client.get(
        "/api/v1/inventory/stock",
        params={"search": "5 litres", "page_size": 100},
        headers=auth_headers(alpha_token),
    ).json()["items"]
    assert large in {row["product_id"] for row in stock}
    assert small not in {row["product_id"] for row in stock}
    assert marker  # le nom seul ramène toujours les deux
    both = api_client.get(
        "/api/v1/products", params={"search": name}, headers=auth_headers(alpha_token)
    ).json()["items"]
    assert {small, large} <= {item["id"] for item in both}


def test_description_search_escapes_wildcards(api_client: TestClient, alpha_token: str) -> None:
    from tests.integration.test_sales_api import _make_product

    marker = uuid4().hex[:6]
    plain = _make_product(api_client, alpha_token, name=f"Savon {marker}", description="lot de 3")
    percent = _make_product(
        api_client, alpha_token, name=f"Savon {marker}", description="remise 10% incluse"
    )
    found = api_client.get(
        "/api/v1/products",
        params={"search": "10%", "page_size": 100},
        headers=auth_headers(alpha_token),
    ).json()["items"]
    ids = {item["id"] for item in found}
    assert percent in ids and plain not in ids
    nothing = api_client.get(
        "/api/v1/products",
        params={"search": "_%", "page_size": 100},
        headers=auth_headers(alpha_token),
    ).json()["items"]
    assert plain not in {item["id"] for item in nothing}


def test_the_description_reaches_stock_scan_and_sale_line(
    api_client: TestClient, alpha_token: str
) -> None:
    from tests.integration.test_sales_api import _add_line, _draft

    _, small, large = _twins(api_client, alpha_token)
    stock = api_client.get(
        "/api/v1/inventory/stock",
        params={"product_id": [small, large]},
        headers=auth_headers(alpha_token),
    ).json()["items"]
    assert {row["product_id"]: row["description"] for row in stock} == {
        small: "1 litre",
        large: "5 litres",
    }

    sku = api_client.get(f"/api/v1/products/{large}", headers=auth_headers(alpha_token)).json()[
        "sku"
    ]
    scanned = api_client.get(
        f"/api/v1/inventory/products/by-barcode/{sku}", headers=auth_headers(alpha_token)
    )
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["description"] == "5 litres"

    sale_id = _draft(api_client, alpha_token)
    line = _add_line(api_client, alpha_token, sale_id, large, qty="1")
    assert line.status_code == 201, line.text
    assert line.json()["product_description"] == "5 litres"


def test_another_company_never_finds_a_product_by_its_description(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    from tests.integration.test_sales_api import _make_product

    secret = f"cuvée {uuid4().hex[:8]}"
    _make_product(api_client, alpha_token, description=secret)
    found = api_client.get(
        "/api/v1/products", params={"search": secret}, headers=auth_headers(beta_token)
    ).json()["items"]
    assert found == []
