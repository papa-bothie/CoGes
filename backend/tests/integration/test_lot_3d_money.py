"""L'argent du lot 3d de la phase 15 (ADR 0073) : écrans 17 à 21.

* l'écran 17 donne vendu − prix d'achat − dépenses = gagné (ou perdu), la plus grosse
  dépense, l'entré et le sorti de la caisse, découpés en moments, jours ou semaines ;
* les cartes du bas disent ce que doivent les clients (les trois premiers) et ce qu'on
  doit aux fournisseurs (par échéance) ;
* l'écran 21 liste les entrées et sorties d'un jour en mots, le net par moyen, et garde
  le paiement annulé à côté de sa ligne inverse, sans les compter ;
* l'écran 20 donne les dépenses du mois par type et les dernières, avec leur moyen ;
* le vendeur ne lit pas l'argent.

Chaque test travaille dans une entreprise neuve : les chiffres y sont exacts.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

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
    company = _create_demo_company(f"lot-3d-{uuid4().hex[:8]}")
    return company, login_token(client, company)


def _get(client: TestClient, token: str, path: str, **params: str) -> dict[str, Any]:
    response = client.get(f"/api/v1{path}", headers=auth_headers(token), params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _today(client: TestClient, token: str) -> date:
    timezone = _get(client, token, "/companies/me")["timezone"]
    return datetime.now(ZoneInfo(timezone)).date()


def _product(client: TestClient, token: str, name: str) -> str:
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"name": name, "unit_price": "1000", "default_tax_rate": "0"},
    )
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    stocked = client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={"product_id": product_id, "type": "initial", "qty_delta": "100", "unit_cost": "600"},
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def _customer(client: TestClient, token: str, name: str) -> str:
    created = client.post("/api/v1/customers", headers=auth_headers(token), json={"name": name})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _supplier(client: TestClient, token: str, name: str) -> str:
    created = client.post("/api/v1/suppliers", headers=auth_headers(token), json={"name": name})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _sell(
    client: TestClient,
    token: str,
    product_id: str,
    qty: str,
    *,
    customer_id: str | None = None,
    paid: str | None = None,
    method: str = "cash",
) -> dict[str, Any]:
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
    total = client.get(f"/api/v1/sales/{sale['id']}", headers=auth_headers(token)).json()["total"]
    confirmed = client.post(
        f"/api/v1/sales/{sale['id']}/confirm",
        headers=write_headers(token),
        json={"paid_amount": paid if paid is not None else total, "method": method},
    )
    assert confirmed.status_code == 200, confirmed.text
    body: dict[str, Any] = confirmed.json()
    return body


def _category(client: TestClient, token: str, name: str, kind: str = "variable") -> str:
    created = client.post(
        "/api/v1/expense-categories",
        headers=auth_headers(token),
        json={"name": name, "kind": kind},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _expense(
    client: TestClient,
    token: str,
    category_id: str,
    label: str,
    amount: str,
    *,
    spent_at: date,
    method: str = "cash",
) -> dict[str, Any]:
    created = client.post(
        "/api/v1/expenses",
        headers=write_headers(token),
        json={
            "category_id": category_id,
            "label": label,
            "amount": amount,
            "spent_at": spent_at.isoformat(),
            "payment": {"method": method},
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def _collect(
    client: TestClient, token: str, debt_id: str, amount: str, method: str = "cash"
) -> dict[str, Any]:
    paid = client.post(
        "/api/v1/payments",
        headers=write_headers(token),
        json={
            "direction": "inflow",
            "method": method,
            "amount": amount,
            "allocations": [{"debt_id": debt_id, "amount": amount}],
        },
    )
    assert paid.status_code == 201, paid.text
    body: dict[str, Any] = paid.json()
    return body


def _open_debt(client: TestClient, token: str, customer_id: str) -> dict[str, Any]:
    debts = _get(client, token, "/debts", customer_id=customer_id)
    first: dict[str, Any] = debts["items"][0]
    return first


# ------------------------------------------------------------------ écran 17


def test_today_sums_up_what_was_won_or_lost(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    today = _today(api_client, token)
    riz = _product(api_client, token, "Riz")
    _sell(api_client, token, riz, "3")  # vendu 3 000, prix d'achat 1 800
    electricite = _category(api_client, token, "Électricité")
    _expense(api_client, token, electricite, "Facture d'électricité", "2000", spent_at=today)
    transport = _category(api_client, token, "Transport")
    _expense(api_client, token, transport, "Taxi", "500", spent_at=today)

    money = _get(api_client, token, "/analytics/money", period="today")
    assert money["period"] == "today"
    assert (money["period_from"], money["period_to"]) == (today.isoformat(), today.isoformat())
    assert Decimal(money["sold"]) == Decimal("3000")
    assert Decimal(money["cogs"]) == Decimal("1800")
    assert Decimal(money["expenses"]) == Decimal("2500")
    assert Decimal(money["result"]) == Decimal("-1300")
    assert money["biggest_expense"]["label"] == "Facture d'électricité"
    assert money["biggest_expense"]["category_name"] == "Électricité"
    assert Decimal(money["biggest_expense"]["amount"]) == Decimal("2000")
    assert Decimal(money["cash_in"]) == Decimal("3000")
    assert Decimal(money["cash_out"]) == Decimal("2500")
    assert Decimal(money["net_cash"]) == Decimal("500")

    # Les quatre moments de la journée, et la caisse retombe juste.
    assert money["grain"] == "moment"
    assert [b["key"] for b in money["buckets"]] == ["morning", "noon", "afternoon", "evening"]
    assert sum(Decimal(b["cash_in"]) for b in money["buckets"]) == Decimal("3000")
    assert sum(Decimal(b["cash_out"]) for b in money["buckets"]) == Decimal("2500")


def test_week_and_month_have_their_own_bars(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    today = _today(api_client, token)
    riz = _product(api_client, token, "Riz")
    _sell(api_client, token, riz, "2")

    week = _get(api_client, token, "/analytics/money", period="week")
    assert week["grain"] == "day"
    assert [b["key"] for b in week["buckets"]] == [
        (today - timedelta(days=6 - i)).isoformat() for i in range(7)
    ]
    assert Decimal(week["buckets"][-1]["cash_in"]) == Decimal("2000")

    month = _get(api_client, token, "/analytics/money", period="month")
    assert month["period_from"] == today.replace(day=1).isoformat()
    assert month["grain"] == "week"
    assert [b["key"] for b in month["buckets"]] == ["week-1", "week-2", "week-3", "week-4"]
    assert month["buckets"][0]["start"] == today.replace(day=1).isoformat()
    assert month["buckets"][3]["start"] == today.replace(day=22).isoformat()
    following = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    assert month["buckets"][3]["end"] == (following - timedelta(days=1)).isoformat()
    assert sum(Decimal(b["cash_in"]) for b in month["buckets"]) == Decimal("2000")


def test_chosen_dates_are_cut_by_day_then_by_week(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    today = _today(api_client, token)

    short = _get(
        api_client,
        token,
        "/analytics/money",
        **{"from": (today - timedelta(days=9)).isoformat(), "to": today.isoformat()},
    )
    assert short["period"] is None
    assert short["grain"] == "day"
    assert len(short["buckets"]) == 10

    long = _get(
        api_client,
        token,
        "/analytics/money",
        **{"from": (today - timedelta(days=39)).isoformat(), "to": today.isoformat()},
    )
    assert long["grain"] == "week"
    assert len(long["buckets"]) == 6  # 40 jours : 5 semaines pleines et 5 jours
    assert long["buckets"][-1]["end"] == today.isoformat()

    missing = api_client.get("/api/v1/analytics/money", headers=auth_headers(token))
    assert missing.status_code == 422, missing.text


def test_what_people_owe_and_what_is_owed_to_suppliers(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    riz = _product(api_client, token, "Riz")
    for name, qty in (("Moussa Fall", "25"), ("Aminata Sow", "12"), ("Awa Diop", "4")):
        _sell(api_client, token, riz, qty, customer_id=_customer(api_client, token, name), paid="0")
    mariama = _customer(api_client, token, "Mariama Diallo")
    _sell(api_client, token, riz, "8", customer_id=mariama, paid="500")

    sandaga = _supplier(api_client, token, "Grossiste Sandaga")
    senegal = _supplier(api_client, token, "Sénégal Distribution")
    today = _today(api_client, token)
    for supplier_id, amount, days in ((senegal, "65000", 12), (sandaga, "120000", 4)):
        debt = api_client.post(
            "/api/v1/debts",
            headers=write_headers(token),
            json={
                "party_type": "supplier",
                "supplier_id": supplier_id,
                "principal": amount,
                "due_date": (today + timedelta(days=days)).isoformat(),
            },
        )
        assert debt.status_code == 201, debt.text

    money = _get(api_client, token, "/analytics/money", period="month")
    receivables = money["receivables"]
    assert Decimal(receivables["total"]) == Decimal("48500")
    assert receivables["count"] == 4
    assert [row["name"] for row in receivables["rows"]] == [
        "Moussa Fall",
        "Aminata Sow",
        "Mariama Diallo",
    ]
    assert Decimal(receivables["rows"][2]["owed"]) == Decimal("7500")
    payables = money["payables"]
    assert Decimal(payables["total"]) == Decimal("185000")
    assert [row["name"] for row in payables["rows"]] == [
        "Grossiste Sandaga",
        "Sénégal Distribution",
    ]
    assert payables["rows"][0]["due_date"] == (today + timedelta(days=4)).isoformat()


# ------------------------------------------------------------------ écran 21


def test_the_cash_journal_speaks_in_words(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    today = _today(api_client, token)
    riz = _product(api_client, token, "Riz")
    awa = _customer(api_client, token, "Awa Diop")
    sale = _sell(api_client, token, riz, "12", customer_id=awa, method="wave")
    _sell(api_client, token, riz, "3")  # client de passage, espèces
    aminata = _customer(api_client, token, "Aminata Sow")
    _sell(api_client, token, riz, "10", customer_id=aminata, paid="0")
    debt = _open_debt(api_client, token, aminata)
    _collect(api_client, token, debt["id"], "6800", method="orange_money")
    electricite = _category(api_client, token, "Électricité")
    expense = _expense(api_client, token, electricite, "Facture", "5000", spent_at=today)

    cash = _get(api_client, token, "/analytics/cash")
    assert cash["day"] == today.isoformat()
    assert Decimal(cash["cash_in"]) == Decimal("21800")
    assert Decimal(cash["cash_out"]) == Decimal("5000")
    assert Decimal(cash["net_cash"]) == Decimal("16800")
    assert {row["method"]: Decimal(row["net"]) for row in cash["by_method"]} == {
        "cash": Decimal("-2000"),
        "wave": Decimal("12000"),
        "orange_money": Decimal("6800"),
    }
    assert [row["method"] for row in cash["by_method"]] == ["cash", "wave", "orange_money"]

    lines = cash["lines"]
    assert [line["kind"] for line in lines] == ["expense", "debt_in", "sale", "sale"]
    spent, collected, walk_in, wave = lines
    assert spent["party_name"] == "Électricité"
    assert spent["expense_label"] == "Facture"
    assert spent["document_no"] == expense["expense_no"]
    assert Decimal(spent["signed_amount"]) == Decimal("-5000")
    assert collected["party_name"] == "Aminata Sow"
    assert collected["method"] == "orange_money"
    assert walk_in["party_name"] is None
    assert wave["party_name"] == "Awa Diop"
    assert wave["document_no"] == sale["sale_no"]
    assert wave["sale_id"] == sale["id"]
    assert all(not line["cancelled"] and not line["is_reversal"] for line in lines)
    assert cash["truncated"] is False


def test_a_cancelled_line_stays_next_to_its_reversal(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    riz = _product(api_client, token, "Riz")
    moussa = _customer(api_client, token, "Moussa Fall")
    _sell(api_client, token, riz, "20", customer_id=moussa, paid="0")
    payment = _collect(api_client, token, _open_debt(api_client, token, moussa)["id"], "15000")

    cancelled = api_client.post(
        f"/api/v1/payments/{payment['id']}/cancel",
        headers=write_headers(token),
        json={"reason": "Erreur de montant"},
    )
    assert cancelled.status_code == 201, cancelled.text

    cash = _get(api_client, token, "/analytics/cash")
    reversal, original = cash["lines"]
    assert original["payment_id"] == payment["id"]
    assert original["cancelled"] is True
    assert reversal["is_reversal"] is True
    assert reversal["reversal_of"] == payment["id"]
    assert reversal["cancel_reason"] == "Erreur de montant"
    assert reversal["kind"] == "debt_in"
    assert reversal["party_name"] == "Moussa Fall"
    assert Decimal(reversal["signed_amount"]) == Decimal("-15000")
    # Ni l'un ni l'autre ne compte : la caisse revient à ce qu'elle était.
    assert Decimal(cash["cash_in"]) == Decimal("0")
    assert Decimal(cash["cash_out"]) == Decimal("0")
    assert cash["by_method"] == []
    # La dette remonte : Moussa Fall doit de nouveau 20 000 F.
    assert Decimal(_open_debt(api_client, token, moussa)["balance"]) == Decimal("20000")


def test_another_day_of_cash(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    today = _today(api_client, token)
    riz = _product(api_client, token, "Riz")
    _sell(api_client, token, riz, "1")

    yesterday = _get(
        api_client, token, "/analytics/cash", day=(today - timedelta(days=1)).isoformat()
    )
    assert yesterday["lines"] == []
    assert Decimal(yesterday["cash_in"]) == Decimal("0")


# ------------------------------------------------------------------ écran 20


def test_expenses_of_the_month_by_type_and_the_latest(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    today = _today(api_client, token)
    loyer = _category(api_client, token, "Loyer", kind="fixed")
    eau = _category(api_client, token, "Eau")
    _category(api_client, token, "Réparations")  # sans dépense : absente
    _expense(api_client, token, eau, "Facture d'eau", "12500", spent_at=today, method="wave")
    _expense(api_client, token, loyer, "Loyer d'octobre", "120000", spent_at=today)
    _expense(api_client, token, eau, "Bidons", "500", spent_at=today, method="orange_money")

    summary = _get(api_client, token, "/analytics/expenses-summary")
    assert summary["period_from"] == today.replace(day=1).isoformat()
    assert Decimal(summary["total"]) == Decimal("133000")
    assert [(row["name"], Decimal(row["total"])) for row in summary["by_category"]] == [
        ("Loyer", Decimal("120000")),
        ("Eau", Decimal("13000")),
    ]
    recent = summary["recent"]
    assert [row["label"] for row in recent] == ["Bidons", "Loyer d'octobre", "Facture d'eau"]
    assert [row["method"] for row in recent] == ["orange_money", "cash", "wave"]


# ------------------------------------------------------------------ droits


def test_the_seller_does_not_read_the_money(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    seller = create_user_with_role(
        api_client, token, company, role="vendeur", email=f"v-{uuid4().hex[:8]}@lot3d.example.com"
    )
    for path, params in (
        ("/analytics/money", {"period": "today"}),
        ("/analytics/cash", {}),
        ("/analytics/expenses-summary", {}),
    ):
        response = api_client.get(f"/api/v1{path}", headers=auth_headers(seller), params=params)
        assert response.status_code == 403, (path, response.text)
