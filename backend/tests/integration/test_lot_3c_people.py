"""Clients et fournisseurs du lot 3c de la phase 15 (ADR 0072) : écrans 13 à 16.

* un fournisseur a une adresse facultative (révision 0018) ;
* la recherche d'un client ou d'un fournisseur trouve aussi son téléphone ;
* la liste dit qui doit combien et depuis quand, ceux qui doivent d'abord, se filtre
  sur « qui me doivent » et se résume ;
* la fiche d'un client donne sa dette, ses achats du mois, sa dernière visite, ses
  achats avec les articles et ses paiements, sur une vente ou sur une dette ;
* la fiche d'un fournisseur donne ce qu'on lui doit, ses livraisons avec leurs articles,
  et nos paiements ;
* un vendeur voit les personnes, jamais l'argent qu'elles doivent.

Chaque test travaille dans une entreprise neuve : les chiffres y sont exacts.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    create_user_with_role,
    login_token,
    write_headers,
)

pytestmark = pytest.mark.integration


def _fresh(client: TestClient) -> tuple[DemoCompany, str]:
    company = _create_demo_company(f"lot-3c-{uuid4().hex[:8]}")
    return company, login_token(client, company)


def _product(client: TestClient, token: str, name: str, *, unit: str = "piece") -> str:
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"name": name, "unit_price": "1000", "default_tax_rate": "0", "unit": unit},
    )
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    stocked = client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={"product_id": product_id, "type": "initial", "qty_delta": "100", "unit_cost": "500"},
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def _customer(client: TestClient, token: str, name: str, phone: str | None = None) -> str:
    body: dict[str, Any] = {"name": name}
    if phone is not None:
        body["phone"] = phone
    created = client.post("/api/v1/customers", headers=auth_headers(token), json=body)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _supplier(client: TestClient, token: str, name: str, phone: str | None = None) -> str:
    body: dict[str, Any] = {"name": name}
    if phone is not None:
        body["phone"] = phone
    created = client.post("/api/v1/suppliers", headers=auth_headers(token), json=body)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _sell(
    client: TestClient,
    token: str,
    lines: list[tuple[str, str]],
    *,
    customer_id: str | None = None,
    paid: str | None = None,
) -> dict[str, Any]:
    """Vente confirmée ; `paid` plus petit que le total ouvre une dette au client."""
    sale = client.post(
        "/api/v1/sales",
        headers=auth_headers(token),
        json={} if customer_id is None else {"customer_id": customer_id},
    ).json()
    for product_id, qty in lines:
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
        json={"paid_amount": paid if paid is not None else detail["total"], "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body: dict[str, Any] = confirmed.json()
    return body


def _debt_of_sale(client: TestClient, token: str, customer_id: str) -> dict[str, Any]:
    debts = client.get(
        "/api/v1/debts", headers=auth_headers(token), params={"customer_id": customer_id}
    ).json()
    assert debts["items"], debts
    first: dict[str, Any] = debts["items"][0]
    return first


def _deliver(
    client: TestClient,
    token: str,
    supplier_id: str,
    lines: list[tuple[str, str, str]],
    *,
    mode: str = "later",
    paid: str | None = None,
    due_in_days: int = 10,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "supplier_id": supplier_id,
        "lines": [{"product_id": p, "qty": q, "unit_cost": c} for p, q, c in lines],
        "payment_mode": mode,
        "method": "cash",
        "due_date": (date.today() + timedelta(days=due_in_days)).isoformat(),
    }
    if paid is not None:
        body["paid_amount"] = paid
    response = client.post("/api/v1/inventory/deliveries", headers=write_headers(token), json=body)
    assert response.status_code == 201, response.text
    delivered: dict[str, Any] = response.json()
    return delivered


def _get(client: TestClient, token: str, path: str, **params: str) -> dict[str, Any]:
    response = client.get(f"/api/v1{path}", headers=auth_headers(token), params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# ------------------------------------------------------------------ adresse


def test_a_supplier_has_an_optional_address(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    supplier_id = _supplier(api_client, token, "Grossiste Sandaga")
    assert _get(api_client, token, f"/suppliers/{supplier_id}")["address"] is None

    changed = api_client.patch(
        f"/api/v1/suppliers/{supplier_id}",
        headers=auth_headers(token),
        json={"address": "  Marché Sandaga, Dakar  "},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["address"] == "Marché Sandaga, Dakar"
    sheet = _get(api_client, token, f"/analytics/suppliers/{supplier_id}")
    assert sheet["address"] == "Marché Sandaga, Dakar"


# ---------------------------------------------------------------- recherche


def test_people_are_found_by_their_phone(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    aminata = _customer(api_client, token, "Aminata Sow", phone="77 655 90 21")
    _customer(api_client, token, "Moussa Fall", phone="76 220 15 90")
    sandaga = _supplier(api_client, token, "Grossiste Sandaga", phone="33 821 45 10")

    found = _get(api_client, token, "/customers", search="77655")
    assert [row["id"] for row in found["items"]] == [aminata]
    found = _get(api_client, token, "/analytics/customers", search="655 90")
    assert [row["id"] for row in found["items"]] == [aminata]
    found = _get(api_client, token, "/suppliers", search="33 821")
    assert [row["id"] for row in found["items"]] == [sandaga]


# -------------------------------------------------------------------- liste


def test_the_customer_list_puts_who_owes_first_and_sums_up(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    product = _product(api_client, token, "Riz brisé 25 kg")
    moussa = _customer(api_client, token, "Moussa Fall")
    aminata = _customer(api_client, token, "Aminata Sow")
    awa = _customer(api_client, token, "Awa Diop")
    ndiaye = _customer(api_client, token, "Boutique Ndiaye")
    _customer(api_client, token, "Zeynab Ka")  # jamais venue
    # Moussa doit 2 500, Aminata 500, Awa rien (payé), la Boutique Ndiaye rien.
    _sell(api_client, token, [(product, "3")], customer_id=moussa, paid="500")
    _sell(api_client, token, [(product, "1")], customer_id=aminata, paid="500")
    _sell(api_client, token, [(product, "1")], customer_id=awa)
    _sell(api_client, token, [(product, "2")], customer_id=ndiaye)

    listing = _get(api_client, token, "/analytics/customers")
    names = [row["name"] for row in listing["items"]]
    assert names[:2] == ["Moussa Fall", "Aminata Sow"]
    # Puis la dernière visite la plus récente d'abord, et qui n'est jamais venu à la fin.
    assert names[2:] == ["Boutique Ndiaye", "Awa Diop", "Zeynab Ka"]
    moussa_row = listing["items"][0]
    assert moussa_row["owed"] == "2500.00"
    assert moussa_row["owed_since"] is not None
    assert moussa_row["last_seen_at"] is not None
    assert listing["items"][-1]["owed"] == "0.00"
    assert listing["items"][-1]["last_seen_at"] is None
    assert listing["owing_count"] == 2
    assert listing["owed_total"] == "3000.00"
    assert listing["customer_count"] == 5
    assert listing["supplier_count"] == 0

    owing = _get(api_client, token, "/analytics/customers", owing="true")
    assert [row["name"] for row in owing["items"]] == ["Moussa Fall", "Aminata Sow"]
    assert owing["total"] == 2


def test_the_supplier_list_gives_what_we_owe_and_when(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz brisé 25 kg", unit="sac")
    sandaga = _supplier(api_client, token, "Grossiste Sandaga")
    _supplier(api_client, token, "Laiterie du Berger")
    _deliver(api_client, token, sandaga, [(rice, "10", "14000")], mode="part", paid="40000")

    listing = _get(api_client, token, "/analytics/suppliers")
    first = listing["items"][0]
    assert first["name"] == "Grossiste Sandaga"
    assert first["owed"] == "100000.00"
    assert first["due_date"] == (date.today() + timedelta(days=10)).isoformat()
    assert first["last_seen_at"] is not None
    assert listing["items"][1]["owed"] == "0.00"
    assert listing["owing_count"] == 1
    assert listing["owed_total"] == "100000.00"
    assert listing["supplier_count"] == 2


# ------------------------------------------------------------- fiche client


def test_the_customer_sheet_tells_debt_month_and_visits(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz brisé 25 kg")
    oil = _product(api_client, token, "Huile Dinor 1 L")
    candles = _product(api_client, token, "Bougies paquet")
    sugar = _product(api_client, token, "Sucre en poudre")
    moussa = _customer(api_client, token, "Moussa Fall", phone="76 220 15 90")
    _sell(api_client, token, [(rice, "1")], customer_id=moussa)
    last = _sell(
        api_client,
        token,
        [(rice, "2"), (oil, "1"), (candles, "1"), (sugar, "1")],
        customer_id=moussa,
        paid="1000",
    )

    sheet = _get(api_client, token, f"/analytics/customers/{moussa}")
    assert sheet["name"] == "Moussa Fall"
    assert sheet["phone"] == "76 220 15 90"
    assert sheet["owed"] == "4000.00"
    assert sheet["owed_since"] is not None
    assert sheet["month_total"] == "6000.00"
    assert sheet["month_visits"] == 2
    assert sheet["last_visit_at"] == last["sold_at"]

    sales = _get(api_client, token, f"/analytics/customers/{moussa}/sales")
    assert sales["total"] == 2
    newest = sales["items"][0]
    assert newest["sale_id"] == last["id"]
    assert newest["balance"] == "4000.00"
    # Les trois premiers articles de la vente, dans l'ordre de saisie, et le nombre total.
    assert newest["item_names"] == ["Riz brisé 25 kg", "Huile Dinor 1 L", "Bougies paquet"]
    assert newest["item_count"] == 4


def test_the_customer_payments_cover_sales_and_debts(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz brisé 25 kg")
    moussa = _customer(api_client, token, "Moussa Fall")
    other = _customer(api_client, token, "Awa Diop")
    sale = _sell(api_client, token, [(rice, "3")], customer_id=moussa, paid="1000")
    _sell(api_client, token, [(rice, "1")], customer_id=other)
    debt = _debt_of_sale(api_client, token, moussa)
    settled = api_client.post(
        "/api/v1/payments",
        headers=write_headers(token),
        json={
            "direction": "inflow",
            "method": "wave",
            "amount": "1500",
            "allocations": [{"debt_id": debt["id"], "amount": "1500"}],
        },
    )
    assert settled.status_code == 201, settled.text

    payments = _get(api_client, token, f"/analytics/customers/{moussa}/payments")
    rows = payments["items"]
    assert payments["total"] == 2
    assert [(row["amount"], row["method"], row["on_debt"]) for row in rows] == [
        ("1500.00", "wave", True),
        ("1000.00", "cash", False),
    ]
    assert {row["sale_no"] for row in rows} == {sale["sale_no"]}
    sheet = _get(api_client, token, f"/analytics/customers/{moussa}")
    assert sheet["owed"] == "500.00"


# --------------------------------------------------------- fiche fournisseur


def test_the_supplier_sheet_tells_deliveries_articles_and_payments(
    api_client: TestClient,
) -> None:
    _, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz brisé 25 kg", unit="sac")
    oil = _product(api_client, token, "Huile Dinor 1 L", unit="bouteille")
    sugar = _product(api_client, token, "Sucre en poudre", unit="kg")
    sandaga = _supplier(api_client, token, "Grossiste Sandaga")
    _deliver(api_client, token, sandaga, [(sugar, "25", "600")], mode="now")
    latest = _deliver(
        api_client,
        token,
        sandaga,
        [(rice, "10", "14000"), (oil, "24", "1150")],
        mode="part",
        paid="47600",
    )

    sheet = _get(api_client, token, f"/analytics/suppliers/{sandaga}")
    assert sheet["owed"] == "120000.00"
    assert sheet["due_date"] == (date.today() + timedelta(days=10)).isoformat()
    assert sheet["month_total"] == "182600.00"
    assert sheet["month_deliveries"] == 2
    assert sheet["product_count"] == 3
    assert set(sheet["product_names"]) == {"Riz brisé 25 kg", "Huile Dinor 1 L", "Sucre en poudre"}

    deliveries = _get(api_client, token, f"/analytics/suppliers/{sandaga}/deliveries")
    newest = deliveries["items"][0]
    assert newest["debt_id"] == latest["debt_id"]
    assert newest["total"] == "167600.00"
    assert newest["balance"] == "120000.00"
    assert [(line["name"], line["qty"], line["unit"]) for line in newest["lines"]] == [
        ("Riz brisé 25 kg", "10.000", "sac"),
        ("Huile Dinor 1 L", "24.000", "bouteille"),
    ]
    assert deliveries["items"][1]["balance"] == "0.00"

    payments = _get(api_client, token, f"/analytics/suppliers/{sandaga}/payments")
    assert [row["amount"] for row in payments["items"]] == ["47600.00", "15000.00"]
    assert payments["items"][0]["debt_id"] == latest["debt_id"]
    assert payments["items"][0]["debt_created_at"] is not None


# ----------------------------------------------------------------- droits


def test_a_salesperson_sees_people_but_not_their_money(
    api_client: TestClient,
) -> None:
    company, token = _fresh(api_client)
    rice = _product(api_client, token, "Riz brisé 25 kg")
    moussa = _customer(api_client, token, "Moussa Fall")
    sandaga = _supplier(api_client, token, "Grossiste Sandaga")
    _sell(api_client, token, [(rice, "3")], customer_id=moussa, paid="500")
    _deliver(api_client, token, sandaga, [(rice, "1", "500")])
    seller = create_user_with_role(
        api_client, token, company, role="vendeur", email=f"v-{uuid4().hex[:8]}@lot3c.example.com"
    )

    listing = _get(api_client, seller, "/analytics/customers")
    assert listing["items"][0]["owed"] is None
    assert listing["owed_total"] is None
    assert listing["owing_count"] is None
    sheet = _get(api_client, seller, f"/analytics/customers/{moussa}")
    assert sheet["owed"] is None
    assert sheet["month_visits"] == 1
    supplier_sheet = _get(api_client, seller, f"/analytics/suppliers/{sandaga}")
    assert supplier_sheet["owed"] is None
    assert supplier_sheet["month_total"] is None
    # Ce qui ne dit que de l'argent dû reste fermé.
    owing = api_client.get(
        "/api/v1/analytics/customers", headers=auth_headers(seller), params={"owing": "true"}
    )
    assert owing.status_code == 403
    deliveries = api_client.get(
        f"/api/v1/analytics/suppliers/{sandaga}/deliveries", headers=auth_headers(seller)
    )
    assert deliveries.status_code == 403


def test_an_unknown_person_is_not_found(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    for path in ("customers", "suppliers"):
        response = api_client.get(
            f"/api/v1/analytics/{path}/{uuid4()}", headers=auth_headers(token)
        )
        assert response.status_code == 404, response.text


def test_amounts_are_decimal_strings(api_client: TestClient) -> None:
    """Jamais de float : les montants sortent en chaînes, comme partout."""
    _, token = _fresh(api_client)
    _customer(api_client, token, "Moussa Fall")
    row = _get(api_client, token, "/analytics/customers")["items"][0]
    assert isinstance(row["owed"], str)
    assert Decimal(row["owed"]) == 0
