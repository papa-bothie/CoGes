"""Stock du lot 3b de la phase 15 (ADR 0071) : écrans 07 à 12 de la maquette v2.

* un rayon a une couleur facultative (1 à 8) et le nombre de ses articles ;
* la liste du stock se filtre (bientôt épuisés, épuisés, rayon, recherche), se trie
  (épuisés d'abord), donne le prix de vente et le niveau rapporté au plus haut stock des
  90 derniers jours, et se résume (nombre d'articles, valeur, alertes) ;
* une livraison fait entrer le stock, ouvre la dette fournisseur et la paie, en une
  seule transaction, tout ou rien, sous clé d'idempotence ;
* l'historique d'un article dit qui a acheté, qui a livré, et pourquoi on a corrigé.

Chaque test travaille dans une entreprise neuve : les chiffres y sont exacts.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    read_scalar_in_tenant,
    write_headers,
)

pytestmark = pytest.mark.integration


def _fresh(client: TestClient) -> tuple[DemoCompany, str]:
    company = _create_demo_company(f"lot-3b-{uuid4().hex[:8]}")
    return company, login_token(client, company)


def _category(client: TestClient, token: str, name: str, color: int | None = None) -> str:
    body: dict[str, Any] = {"name": name}
    if color is not None:
        body["color"] = color
    created = client.post("/api/v1/categories", headers=auth_headers(token), json=body)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _product(
    client: TestClient,
    token: str,
    name: str,
    *,
    price: str = "1000",
    stock: str = "10",
    reorder_point: str | None = "3",
    category_id: str | None = None,
    unit: str = "piece",
) -> str:
    body: dict[str, Any] = {
        "name": name,
        "unit_price": price,
        "default_tax_rate": "0",
        "unit": unit,
    }
    if reorder_point is not None:
        body["reorder_point"] = reorder_point
    if category_id is not None:
        body["category_id"] = category_id
    created = client.post("/api/v1/products", headers=auth_headers(token), json=body)
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    if Decimal(stock) > 0:
        stocked = client.post(
            "/api/v1/inventory/movements",
            headers=auth_headers(token),
            json={
                "product_id": product_id,
                "type": "initial",
                "qty_delta": stock,
                "unit_cost": "500",
            },
        )
        assert stocked.status_code == 201, stocked.text
    return product_id


def _supplier(client: TestClient, token: str, name: str = "Grossiste Sandaga") -> str:
    created = client.post("/api/v1/suppliers", headers=auth_headers(token), json={"name": name})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _customer(client: TestClient, token: str, name: str) -> str:
    created = client.post(
        "/api/v1/customers",
        headers=auth_headers(token),
        json={"name": name, "credit_limit": "1000000"},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _sell(
    client: TestClient,
    token: str,
    product_id: str,
    qty: str,
    *,
    customer_id: str | None = None,
) -> str:
    sale = client.post(
        "/api/v1/sales",
        headers=auth_headers(token),
        json={} if customer_id is None else {"customer_id": customer_id},
    ).json()
    line = client.post(
        f"/api/v1/sales/{sale['id']}/items",
        headers=auth_headers(token),
        json={"product_id": product_id, "qty": qty},
    )
    assert line.status_code == 201, line.text
    detail = client.get(f"/api/v1/sales/{sale['id']}", headers=auth_headers(token)).json()
    confirmed = client.post(
        f"/api/v1/sales/{sale['id']}/confirm",
        headers=write_headers(token),
        json={"paid_amount": detail["total"], "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return str(sale["id"])


def _stock(client: TestClient, token: str, **params: str) -> dict[str, Any]:
    response = client.get(
        "/api/v1/inventory/stock",
        headers=auth_headers(token),
        params={"page_size": "100", **params},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# -------------------------------------------------------------------- rayons


def test_a_shelf_has_an_optional_color(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    colored = _category(api_client, token, "Céréales", color=1)
    plain = _category(api_client, token, "Huiles")

    listed = api_client.get("/api/v1/categories", headers=auth_headers(token)).json()["items"]
    colors = {item["name"]: item["color"] for item in listed}
    assert colors == {"Céréales": 1, "Huiles": None}

    changed = api_client.patch(
        f"/api/v1/categories/{plain}", headers=auth_headers(token), json={"color": 8}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["color"] == 8
    cleared = api_client.patch(
        f"/api/v1/categories/{colored}", headers=auth_headers(token), json={"color": None}
    )
    assert cleared.json()["color"] is None

    for wrong in (0, 9):
        refused = api_client.post(
            "/api/v1/categories", headers=auth_headers(token), json={"name": "X", "color": wrong}
        )
        assert refused.status_code == 422


def test_each_shelf_counts_its_articles(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    cereals = _category(api_client, token, "Céréales")
    empty = _category(api_client, token, "Produits frais")
    _product(api_client, token, "Riz", category_id=cereals)
    _product(api_client, token, "Mil", category_id=cereals)

    response = api_client.get("/api/v1/products/category-counts", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    counts = {item["category_id"]: item["product_count"] for item in response.json()["items"]}
    assert counts[cereals] == 2
    assert counts.get(empty, 0) == 0


# --------------------------------------------------------------- liste du stock


def test_the_stock_list_filters_sorts_and_prices(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    cereals = _category(api_client, token, "Céréales")
    rice = _product(api_client, token, "Riz brisé", price="15500", stock="2", category_id=cereals)
    milk = _product(api_client, token, "Lait en poudre", stock="1")
    _sell(api_client, token, milk, "1")
    soap = _product(api_client, token, "Savon", price="300", stock="60")

    all_lines = _stock(api_client, token)["items"]
    assert [line["product_id"] for line in all_lines] == [milk, rice, soap]
    assert [line["status"] for line in all_lines] == ["out", "low", "ok"]
    assert Decimal(all_lines[1]["unit_price"]) == Decimal("15500")

    assert [line["product_id"] for line in _stock(api_client, token, status="low")["items"]] == [
        rice
    ]
    assert [line["product_id"] for line in _stock(api_client, token, status="out")["items"]] == [
        milk
    ]
    assert [
        line["product_id"] for line in _stock(api_client, token, category_id=cereals)["items"]
    ] == [rice]
    assert [line["product_id"] for line in _stock(api_client, token, search="savon")["items"]] == [
        soap
    ]


def test_the_level_compares_today_with_the_highest_stock_of_90_days(
    api_client: TestClient,
) -> None:
    _company, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz", stock="10")
    _sell(api_client, token, rice, "8")
    untouched = _product(api_client, token, "Bougies", stock="5")

    lines = {line["product_id"]: line for line in _stock(api_client, token)["items"]}
    assert Decimal(lines[rice]["level"]) == Decimal("0.20")
    assert Decimal(lines[untouched]["level"]) == Decimal("1.00")


def test_the_stock_summary_counts_and_values(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    _product(api_client, token, "Riz", stock="2")  # 2 × 500, bientôt épuisé
    milk = _product(api_client, token, "Lait", stock="1")
    _sell(api_client, token, milk, "1")  # épuisé
    _product(api_client, token, "Savon", stock="10")  # 10 × 500

    response = api_client.get("/api/v1/inventory/stock/summary", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["product_count"] == 3
    assert Decimal(body["stock_value"]) == Decimal("6000.00")
    assert body["low_count"] == 1
    assert body["out_count"] == 1


# --------------------------------------------------------------------- livraison


def _deliver(client: TestClient, token: str, body: dict[str, Any], key: str | None = None) -> Any:
    return client.post("/api/v1/inventory/deliveries", headers=write_headers(token, key), json=body)


def test_a_delivery_paid_later_opens_the_supplier_debt(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    company, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz", stock="2")
    oil = _product(api_client, token, "Huile", stock="4")
    supplier = _supplier(api_client, token)
    due = (date.today() + timedelta(days=15)).isoformat()

    response = _deliver(
        api_client,
        token,
        {
            "supplier_id": supplier,
            "lines": [
                {"product_id": rice, "qty": "10", "unit_cost": "14000"},
                {"product_id": oil, "qty": "24", "unit_cost": "1150"},
            ],
            "payment_mode": "later",
            "due_date": due,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["total"]) == Decimal("167600.00")
    assert Decimal(body["paid"]) == Decimal("0")
    assert Decimal(body["balance"]) == Decimal("167600.00")
    assert body["due_date"] == due

    lines = {line["product_id"]: line for line in _stock(api_client, token)["items"]}
    assert Decimal(lines[rice]["qty_on_hand"]) == Decimal("12")
    # CMP : (2 × 500 + 10 × 14 000) / 12.
    assert Decimal(lines[rice]["avg_cost"]).quantize(Decimal("0.01")) == Decimal("11750.00")

    debt = api_client.get(
        "/api/v1/debts",
        headers=auth_headers(token),
        params={"party_type": "supplier", "supplier_id": supplier},
    ).json()["items"]
    assert [(d["id"], Decimal(d["balance"]), d["due_date"]) for d in debt] == [
        (body["debt_id"], Decimal("167600.00"), due)
    ]
    linked = read_scalar_in_tenant(
        session_factory,
        company.company_id,
        "SELECT count(*) FROM inventory_movements "
        "WHERE ref_type = 'supplier_debt' AND ref_id = :debt AND type = 'purchase_in'",
        {"debt": body["debt_id"]},
    )
    assert linked == 2


def test_a_delivery_paid_now_or_in_part_settles_its_debt(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz", stock="0", reorder_point=None)
    supplier = _supplier(api_client, token)
    line = [{"product_id": rice, "qty": "10", "unit_cost": "1000"}]

    now = _deliver(
        api_client,
        token,
        {"supplier_id": supplier, "lines": line, "payment_mode": "now", "method": "wave"},
    )
    assert now.status_code == 201, now.text
    assert Decimal(now.json()["balance"]) == Decimal("0")

    part = _deliver(
        api_client,
        token,
        {
            "supplier_id": supplier,
            "lines": line,
            "payment_mode": "part",
            "paid_amount": "4000",
            "method": "cash",
        },
    )
    assert part.status_code == 201, part.text
    assert Decimal(part.json()["paid"]) == Decimal("4000.00")
    assert Decimal(part.json()["balance"]) == Decimal("6000.00")

    for wrong in ("0", "10000", "12000"):
        refused = _deliver(
            api_client,
            token,
            {
                "supplier_id": supplier,
                "lines": line,
                "payment_mode": "part",
                "paid_amount": wrong,
            },
        )
        assert refused.status_code == 422, refused.text


def test_a_refused_delivery_leaves_no_stock(api_client: TestClient, beta_token: str) -> None:
    """Fournisseur d'une autre entreprise : 404, et aucun mouvement n'est resté."""
    _company, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz", stock="2")
    foreign = _supplier(api_client, beta_token, name=f"Ailleurs {uuid4().hex[:6]}")

    refused = _deliver(
        api_client,
        token,
        {
            "supplier_id": foreign,
            "lines": [{"product_id": rice, "qty": "10", "unit_cost": "1000"}],
            "payment_mode": "later",
        },
    )
    assert refused.status_code == 404, refused.text
    lines = {line["product_id"]: line for line in _stock(api_client, token)["items"]}
    assert Decimal(lines[rice]["qty_on_hand"]) == Decimal("2")


def test_a_replayed_delivery_is_recorded_once(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz", stock="2")
    supplier = _supplier(api_client, token)
    body = {
        "supplier_id": supplier,
        "lines": [{"product_id": rice, "qty": "10", "unit_cost": "1000"}],
        "payment_mode": "later",
    }
    key = uuid4().hex
    first = _deliver(api_client, token, body, key)
    second = _deliver(api_client, token, body, key)
    assert first.status_code == 201, first.text
    assert second.json()["debt_id"] == first.json()["debt_id"]
    lines = {line["product_id"]: line for line in _stock(api_client, token)["items"]}
    assert Decimal(lines[rice]["qty_on_hand"]) == Decimal("12")


# --------------------------------------------------------- historique d'un article


def test_the_history_says_who_bought_who_delivered_and_why(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz", stock="5")
    awa = _customer(api_client, token, "Awa Diop")
    _sell(api_client, token, rice, "1", customer_id=awa)
    _sell(api_client, token, rice, "2")
    supplier = _supplier(api_client, token, "Grossiste Sandaga")
    delivered = _deliver(
        api_client,
        token,
        {
            "supplier_id": supplier,
            "lines": [{"product_id": rice, "qty": "10", "unit_cost": "1000"}],
            "payment_mode": "later",
        },
    )
    assert delivered.status_code == 201, delivered.text
    lost = api_client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={"product_id": rice, "reason_code": "damaged", "qty_delta": "-1"},
    )
    assert lost.status_code == 201, lost.text

    response = api_client.get(
        f"/api/v1/analytics/products/{rice}/history", headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    rows = [
        (item["type"], item["counterparty"], item["reason_code"], Decimal(item["qty_delta"]))
        for item in body["items"]
    ]
    assert rows == [
        ("loss", None, "damaged", Decimal("-1")),
        ("purchase_in", "Grossiste Sandaga", None, Decimal("10")),
        ("sale_out", None, None, Decimal("-2")),
        ("sale_out", "Awa Diop", None, Decimal("-1")),
        ("initial", None, None, Decimal("5")),
    ]
    assert Decimal(body["month_sold_qty"]) == Decimal("3")
    assert body["month_days"] >= 1


def test_the_history_of_another_company_s_article_is_not_found(
    api_client: TestClient, beta_token: str
) -> None:
    _company, token = _fresh(api_client)
    foreign = _product(api_client, beta_token, f"Ailleurs {uuid4().hex[:6]}", stock="1")
    response = api_client.get(
        f"/api/v1/analytics/products/{foreign}/history", headers=auth_headers(token)
    )
    assert response.status_code == 404


def test_an_article_without_stock_still_shows(api_client: TestClient) -> None:
    """Un article jamais entré en stock, ou non suivi, reste visible sur l'écran Stock."""
    _company, token = _fresh(api_client)
    empty = _product(api_client, token, "Bougies", stock="0")
    service = api_client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"name": "Recharge téléphone", "unit_price": "500", "is_stock_tracked": False},
    ).json()["id"]

    lines = {line["product_id"]: line for line in _stock(api_client, token)["items"]}
    assert lines[empty]["status"] == "out"
    assert lines[empty]["is_stock_tracked"] is True
    assert Decimal(lines[empty]["qty_on_hand"]) == Decimal("0")
    assert lines[service]["is_stock_tracked"] is False
    assert lines[service]["status"] == "ok"

    summary = api_client.get("/api/v1/inventory/stock/summary", headers=auth_headers(token)).json()
    assert summary["product_count"] == 2
    assert summary["out_count"] == 1
