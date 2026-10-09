"""Lectures du lot 3a de la phase 15 (ADR 0070) : accueil, ventes et reçu de la maquette v2.

* les coordonnées de la boutique (adresse, téléphone, NINEA, RC, message de bas de reçu)
  se règlent par `PATCH /companies/me` et s'impriment sur le reçu ;
* le reçu et la fiche nomment le vendeur, le reçu donne le téléphone du client ;
* l'accueil dit ce qu'il y a dans la caisse, combien de clients doivent, ce qu'il faut
  surveiller, et l'état de paiement de chaque dernière vente ;
* la liste des ventes se filtre par état, se cherche par nom de client et compte ses
  articles ; les totaux par jour viennent du serveur.

Chaque test qui lit un total travaille dans une entreprise neuve : les chiffres y sont
exacts, sans dépendre des autres tests.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import cache
from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    create_user_with_role,
    login_token,
    write_headers,
)

pytestmark = pytest.mark.integration


# ------------------------------------------------------------------ outillage


def _fresh(client: TestClient) -> tuple[DemoCompany, str]:
    company = _create_demo_company(f"lot-3a-{uuid4().hex[:8]}")
    return company, login_token(client, company)


def _product(
    client: TestClient,
    token: str,
    *,
    name: str | None = None,
    price: str = "1000",
    stock: str = "100",
    reorder_point: str | None = None,
    unit: str = "piece",
) -> str:
    body: dict[str, Any] = {
        "name": name or f"Article {uuid4().hex[:6]}",
        "unit_price": price,
        "default_tax_rate": "0",
        "unit": unit,
    }
    if reorder_point is not None:
        body["reorder_point"] = reorder_point
    created = client.post("/api/v1/products", headers=auth_headers(token), json=body)
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    stocked = client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={"product_id": product_id, "type": "initial", "qty_delta": stock, "unit_cost": "500"},
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def _customer(client: TestClient, token: str, name: str, phone: str | None = None) -> str:
    body: dict[str, Any] = {"name": name, "credit_limit": "1000000"}
    if phone is not None:
        body["phone"] = phone
    created = client.post("/api/v1/customers", headers=auth_headers(token), json=body)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _sale(
    client: TestClient,
    token: str,
    lines: list[tuple[str, str]],
    *,
    paid: str,
    customer_id: str | None = None,
    method: str = "cash",
) -> str:
    sale = client.post(
        "/api/v1/sales",
        headers=auth_headers(token),
        json={} if customer_id is None else {"customer_id": customer_id},
    )
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])
    for product_id, qty in lines:
        line = client.post(
            f"/api/v1/sales/{sale_id}/items",
            headers=auth_headers(token),
            json={"product_id": product_id, "qty": qty},
        )
        assert line.status_code == 201, line.text
    confirmed = client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(token),
        json={"paid_amount": paid, "method": method},
    )
    assert confirmed.status_code == 200, confirmed.text
    return sale_id


def _dashboard(client: TestClient, token: str, company: DemoCompany) -> dict[str, Any]:
    cache.invalidate(company.company_id, cache.DASHBOARD_KEY)
    response = client.get("/api/v1/dashboard", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# ------------------------------------------------------- coordonnées et reçu


SHOP = {
    "address": "Marché HLM 5, Dakar",
    "phone": "77 123 45 67",
    "wave_number": "77 123 45 67",
    "ninea": "0012345678",
    "rc": "SN-DKR-2024-A-1234",
    "receipt_footer": "Merci de votre visite !",
}


def test_shop_details_are_saved_and_printed_on_the_receipt(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    updated = api_client.patch("/api/v1/companies/me", headers=auth_headers(token), json=SHOP)
    assert updated.status_code == 200, updated.text
    assert {key: updated.json()[key] for key in SHOP} == SHOP

    product_id = _product(api_client, token, name="Riz brisé 25 kg", price="15500")
    customer_id = _customer(api_client, token, "Moussa Fall", phone="76 220 15 90")
    sale_id = _sale(api_client, token, [(product_id, "1")], paid="0", customer_id=customer_id)

    receipt = api_client.get(f"/api/v1/sales/{sale_id}/receipt", headers=auth_headers(token))
    assert receipt.status_code == 200, receipt.text
    body = receipt.json()
    assert {key: body["company"][key] for key in SHOP} == SHOP
    assert body["customer"]["phone"] == "76 220 15 90"
    assert body["seller_name"] == "Gérante de test"

    detail = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(token)).json()
    assert detail["seller_name"] == "Gérante de test"


def test_shop_details_are_optional_and_blank_means_none(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    blank = api_client.patch(
        "/api/v1/companies/me", headers=auth_headers(token), json={"address": "   ", "rc": None}
    )
    assert blank.status_code == 200, blank.text
    assert blank.json()["address"] is None
    assert blank.json()["rc"] is None


def test_an_overlong_shop_detail_is_refused(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    response = api_client.patch(
        "/api/v1/companies/me", headers=auth_headers(token), json={"receipt_footer": "x" * 301}
    )
    assert response.status_code == 422


def test_a_shop_detail_change_is_audited(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    api_client.patch("/api/v1/companies/me", headers=auth_headers(token), json={"ninea": "42"})
    logs = api_client.get(
        "/api/v1/audit-logs",
        headers=auth_headers(token),
        params={"entity_table": "companies", "page_size": 10},
    )
    assert logs.status_code == 200, logs.text
    assert any(
        (item["diff"] or {}).get("after") == {"ninea": "42"} for item in logs.json()["items"]
    )


def test_a_seller_cannot_change_the_shop_details(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    seller = create_user_with_role(
        api_client, token, company, role="vendeur", email=f"v-{uuid4().hex[:6]}@example.com"
    )
    response = api_client.patch(
        "/api/v1/companies/me", headers=auth_headers(seller), json={"phone": "70 000 00 00"}
    )
    assert response.status_code == 403


# ------------------------------------------------------------------- accueil


def test_cash_on_hand_is_everything_in_minus_everything_out(api_client: TestClient) -> None:
    """Ventes encaissées (espèces et Wave) moins une dépense payée ; un paiement annulé
    ne compte pas, la part à crédit non plus."""
    company, token = _fresh(api_client)
    product_id = _product(api_client, token, price="1000")
    _sale(api_client, token, [(product_id, "3")], paid="3000")
    _sale(api_client, token, [(product_id, "2")], paid="2000", method="wave")
    customer_id = _customer(api_client, token, "Awa Diop")
    _sale(api_client, token, [(product_id, "5")], paid="1000", customer_id=customer_id)
    cancelled = _sale(api_client, token, [(product_id, "1")], paid="1000")
    detail = api_client.get(f"/api/v1/sales/{cancelled}", headers=auth_headers(token)).json()
    undone = api_client.post(
        f"/api/v1/payments/{detail['payments'][0]['id']}/cancel",
        headers=write_headers(token),
        json={"reason": "Saisie en double"},
    )
    assert undone.status_code == 201, undone.text

    category = api_client.post(
        "/api/v1/expense-categories",
        headers=auth_headers(token),
        json={"name": "Électricité", "kind": "fixed"},
    )
    assert category.status_code == 201, category.text
    expense = api_client.post(
        "/api/v1/expenses",
        headers=write_headers(token),
        json={
            "category_id": category.json()["id"],
            "label": "Facture du mois",
            "amount": "1500",
            "spent_at": datetime.now(UTC).date().isoformat(),
            "payment": {"method": "cash"},
        },
    )
    assert expense.status_code == 201, expense.text

    body = _dashboard(api_client, token, company)
    assert Decimal(body["cash_on_hand"]) == Decimal("4500.00")  # 3 000 + 2 000 + 1 000 − 1 500


def test_receivables_say_how_many_customers_owe(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    product_id = _product(api_client, token, price="1000")
    for name in ("Awa Diop", "Moussa Fall"):
        customer_id = _customer(api_client, token, name)
        _sale(api_client, token, [(product_id, "2")], paid="0", customer_id=customer_id)
        # Deux dettes pour le même client : il compte une fois.
        _sale(api_client, token, [(product_id, "1")], paid="0", customer_id=customer_id)

    body = _dashboard(api_client, token, company)
    assert body["receivables_customer_count"] == 2
    assert Decimal(body["receivables_open"]) == Decimal("6000.00")


def test_watch_lists_low_stock_first_and_the_largest_debt(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    _product(api_client, token, name="Riz brisé 25 kg", stock="2", reorder_point="5", unit="sac")
    _product(api_client, token, name="Huile Dinor 1 L", stock="4", reorder_point="5")
    _product(api_client, token, name="Sucre 1 kg", stock="3", reorder_point="5")
    _product(api_client, token, name="Savon", stock="60", reorder_point="5")
    selling = _product(api_client, token, price="5000")
    small = _customer(api_client, token, "Awa Diop")
    big = _customer(api_client, token, "Moussa Fall")
    _sale(api_client, token, [(selling, "1")], paid="0", customer_id=small)
    _sale(api_client, token, [(selling, "5")], paid="0", customer_id=big)

    body = _dashboard(api_client, token, company)
    stock = body["watch_stock"]
    assert [item["name"] for item in stock] == ["Riz brisé 25 kg", "Sucre 1 kg"]
    assert stock[0]["unit"] == "sac"
    assert Decimal(stock[0]["qty_on_hand"]) == Decimal("2")
    assert stock[0]["status"] == "low"
    assert body["stock_alert_count"] == 3

    debt = body["watch_debt"]
    assert debt["customer_name"] == "Moussa Fall"
    assert Decimal(debt["balance"]) == Decimal("25000.00")
    assert debt["days"] == 0


def test_watch_debt_is_null_when_nobody_owes(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    body = _dashboard(api_client, token, company)
    assert body["watch_debt"] is None
    assert body["watch_stock"] == []
    assert Decimal(body["cash_on_hand"]) == Decimal("0")


def test_recent_sales_carry_their_payment_state(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    product_id = _product(api_client, token, price="1000")
    customer_id = _customer(api_client, token, "Moussa Fall")
    _sale(api_client, token, [(product_id, "2")], paid="2000")
    _sale(api_client, token, [(product_id, "5")], paid="3000", customer_id=customer_id)

    recent = _dashboard(api_client, token, company)["recent_sales"]
    owing, paid = recent[0], recent[1]
    assert owing["status"] == "confirmed"
    assert Decimal(owing["balance"]) == Decimal("2000.00")
    assert owing["debt_status"] == "open"
    assert owing["has_returns"] is False
    assert Decimal(paid["balance"]) == Decimal("0.00")
    assert paid["debt_status"] is None


# ----------------------------------------------------------- liste des ventes


def _numbers(client: TestClient, token: str, **params: str) -> list[str]:
    response = client.get(
        "/api/v1/sales", headers=auth_headers(token), params={"page_size": "100", **params}
    )
    assert response.status_code == 200, response.text
    return [item["sale_no"] for item in response.json()["items"]]


def test_the_sales_list_filters_by_payment_state(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    product_id = _product(api_client, token, price="1000")
    customer_id = _customer(api_client, token, "Moussa Fall")

    paid = _sale(api_client, token, [(product_id, "1")], paid="1000")
    owing = _sale(api_client, token, [(product_id, "2")], paid="500", customer_id=customer_id)
    returned = _sale(api_client, token, [(product_id, "2")], paid="2000")
    back = api_client.post(
        f"/api/v1/sales/{returned}/returns",
        headers=write_headers(token),
        json={
            "lines": [
                {
                    "sale_item_id": api_client.get(
                        f"/api/v1/sales/{returned}", headers=auth_headers(token)
                    ).json()["items"][0]["id"],
                    "qty": "1",
                }
            ],
            "reason": "Abîmé",
        },
    )
    assert back.status_code == 201, back.text
    cancelled = _sale(api_client, token, [(product_id, "1")], paid="0", customer_id=customer_id)
    undone = api_client.post(
        f"/api/v1/sales/{cancelled}/cancel",
        headers=write_headers(token),
        json={"reason": "Erreur de saisie"},
    )
    assert undone.status_code == 200, undone.text

    numbers = {
        sale_id: api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(token)).json()[
            "sale_no"
        ]
        for sale_id in (paid, owing, returned, cancelled)
    }
    assert set(_numbers(api_client, token, state="paid")) == {numbers[paid], numbers[returned]}
    assert _numbers(api_client, token, state="unpaid") == [numbers[owing]]
    assert _numbers(api_client, token, state="returned") == [numbers[returned]]
    assert _numbers(api_client, token, state="cancelled") == [numbers[cancelled]]


def test_the_sales_list_finds_a_customer_by_name_and_a_number(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    product_id = _product(api_client, token, price="1000")
    moussa = _customer(api_client, token, "Moussa Fall")
    awa = _customer(api_client, token, "Awa Diop")
    first = _sale(api_client, token, [(product_id, "1")], paid="1000", customer_id=moussa)
    _sale(api_client, token, [(product_id, "1")], paid="1000", customer_id=awa)
    number = api_client.get(f"/api/v1/sales/{first}", headers=auth_headers(token)).json()["sale_no"]

    assert _numbers(api_client, token, search="moussa") == [number]
    assert _numbers(api_client, token, search=number) == [number]
    # Le numéro se tape aussi sans préfixe ni zéros : « 1 » pour V-000001.
    assert _numbers(api_client, token, search=str(int(number.split("-")[1]))) == [number]


def test_each_sale_counts_its_lines(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    first = _product(api_client, token)
    second = _product(api_client, token)
    third = _product(api_client, token)
    _sale(api_client, token, [(first, "1"), (second, "5"), (third, "5")], paid="11000")

    items = api_client.get("/api/v1/sales", headers=auth_headers(token)).json()["items"]
    assert items[0]["item_count"] == 3


def test_day_totals_count_confirmed_sales_per_local_day(api_client: TestClient) -> None:
    _company, token = _fresh(api_client)
    product_id = _product(api_client, token, price="1000")
    _sale(api_client, token, [(product_id, "2")], paid="2000")
    _sale(api_client, token, [(product_id, "3")], paid="3000")
    customer_id = _customer(api_client, token, "Awa Diop")
    cancelled = _sale(api_client, token, [(product_id, "1")], paid="0", customer_id=customer_id)
    api_client.post(
        f"/api/v1/sales/{cancelled}/cancel",
        headers=write_headers(token),
        json={"reason": "Erreur de saisie"},
    )

    today = datetime.now(UTC).date()
    response = api_client.get(
        "/api/v1/sales/day-totals",
        headers=auth_headers(token),
        params={
            "date_from": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            "date_to": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    days = response.json()["items"]
    assert len(days) == 1
    assert date.fromisoformat(days[0]["day"]) in {today, today + timedelta(days=1)}
    # La maquette compte l'annulée dans le groupe (« 3 ventes ») mais pas dans le total.
    assert days[0]["sale_count"] == 3
    assert days[0]["confirmed_count"] == 2
    assert Decimal(days[0]["total"]) == Decimal("5000.00")

    # Mêmes filtres que la liste : les seules annulées, puis le nom d'un client.
    window = {
        "date_from": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        "date_to": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    }
    cancelled_only = api_client.get(
        "/api/v1/sales/day-totals",
        headers=auth_headers(token),
        params={**window, "state": "cancelled"},
    ).json()["items"]
    assert [(d["sale_count"], d["confirmed_count"], d["total"]) for d in cancelled_only] == [
        (1, 0, "0.00")
    ]
    by_name = api_client.get(
        "/api/v1/sales/day-totals",
        headers=auth_headers(token),
        params={**window, "search": "Awa Diop"},
    ).json()["items"]
    assert [d["sale_count"] for d in by_name] == [1]


def test_day_totals_need_sales_read(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/sales/day-totals")
    assert response.status_code == 401


def test_the_list_can_hide_drafts_and_find_my_own(api_client: TestClient) -> None:
    """La liste de la maquette ne montre pas les brouillons ; « Nouvelle vente » reprend le
    brouillon de la personne connectée, jamais celui d'un collègue."""
    company, token = _fresh(api_client)
    product_id = _product(api_client, token)
    _sale(api_client, token, [(product_id, "1")], paid="1000")
    mine = api_client.post("/api/v1/sales", headers=auth_headers(token), json={}).json()["id"]
    seller = create_user_with_role(
        api_client, token, company, role="vendeur", email=f"v-{uuid4().hex[:6]}@example.com"
    )
    theirs = api_client.post("/api/v1/sales", headers=auth_headers(seller), json={}).json()["id"]

    def ids(user_token: str, **params: str) -> list[str]:
        response = api_client.get("/api/v1/sales", headers=auth_headers(user_token), params=params)
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()["items"]]

    assert mine not in ids(token, include_drafts="false")
    assert theirs not in ids(token, include_drafts="false")
    assert len(ids(token, include_drafts="false")) == 1
    assert {mine, theirs} <= set(ids(token))
    assert ids(token, status="draft", mine="true") == [mine]
    assert ids(seller, status="draft", mine="true") == [theirs]
