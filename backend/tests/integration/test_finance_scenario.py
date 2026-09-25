"""Le scénario d'acceptation de la phase 07, d'un bout à l'autre.

Deux ventes à crédit, un versement réparti sur les deux dettes, le même versement
renvoyé une seconde fois avec la même clé, une charge, une dette fournisseur, et
enfin l'état de l'argent sur la période.

Un seul test, volontairement long : ce qui est mesuré ici n'est aucune règle prise
isolément — elles ont chacune leur fichier — mais le fait qu'elles tiennent
**ensemble**, dans l'ordre où un gérant les rencontre.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant, write_headers
from tests.integration import facts_harness as facts

pytestmark = pytest.mark.integration


def _credit_sale(
    client: TestClient, token: str, product_id: str, customer_id: str, qty: str
) -> dict[str, Any]:
    """Une vente entièrement à crédit : rien n'est encaissé, tout devient dette."""
    sale = client.post(
        "/api/v1/sales", headers=auth_headers(token), json={"customer_id": customer_id}
    )
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])

    line = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(token),
        json={"product_id": product_id, "qty": qty},
    )
    assert line.status_code == 201, line.text

    confirmed = client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(token),
        json={"paid_amount": "0", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body: dict[str, Any] = confirmed.json()
    return body


def test_the_acceptance_scenario_end_to_end(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> None:
    """Deux crédits, un règlement réparti, un rejeu, une charge, un état."""
    headers = auth_headers(alpha_token)
    today = date.today().isoformat()

    # --- le décor : un client sans plafond, un produit en stock ---------------
    customer = api_client.post(
        "/api/v1/customers", headers=headers, json={"name": f"Client {uuid4().hex[:8]}"}
    )
    assert customer.status_code == 201, customer.text
    customer_id = str(customer.json()["id"])

    marker = uuid4().hex[:8]
    product = api_client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": f"SKU-{marker}",
            "name": f"Produit {marker}",
            "unit_price": "1000.00",
            "default_tax_rate": "0",
        },
    )
    assert product.status_code == 201, product.text
    product_id = str(product.json()["id"])
    stocked = api_client.post(
        "/api/v1/inventory/movements",
        headers=headers,
        json={
            "product_id": product_id,
            "type": "initial",
            "qty_delta": "50",
            "unit_cost": "600.00",
        },
    )
    assert stocked.status_code == 201, stocked.text

    # --- 1. deux ventes à crédit : 3 000 et 2 000 ----------------------------
    first_sale = _credit_sale(api_client, alpha_token, product_id, customer_id, "3")
    second_sale = _credit_sale(api_client, alpha_token, product_id, customer_id, "2")

    debts = api_client.get(
        "/api/v1/debts?party_type=customer&status=open&page_size=100", headers=headers
    )
    assert debts.status_code == 200, debts.text
    by_sale = {item["sale_id"]: item for item in debts.json()["items"]}
    first_debt = by_sale[first_sale["id"]]
    second_debt = by_sale[second_sale["id"]]
    assert Decimal(first_debt["balance"]) == Decimal("3000.00")
    assert Decimal(second_debt["balance"]) == Decimal("2000.00")

    # --- 2. un versement de 4 000 réparti sur les deux dettes ----------------
    key = uuid4().hex
    body = {
        "direction": "inflow",
        "method": "mobile_money",
        "amount": "4000.00",
        "allocations": [
            {"debt_id": first_debt["id"], "amount": "3000.00"},
            {"debt_id": second_debt["id"], "amount": "1000.00"},
        ],
    }
    paid = api_client.post("/api/v1/payments", headers=write_headers(alpha_token, key), json=body)
    assert paid.status_code == 201, paid.text
    payment_id = str(paid.json()["id"])

    settled = api_client.get(f"/api/v1/debts/{first_debt['id']}", headers=headers).json()
    partial = api_client.get(f"/api/v1/debts/{second_debt['id']}", headers=headers).json()
    assert settled["status"] == "paid" and settled["closed_at"] is not None
    assert partial["status"] == "partially_paid"
    assert Decimal(partial["balance"]) == Decimal("1000.00")

    # --- 3. la même requête, la même clé : rien de nouveau -------------------
    replayed = api_client.post(
        "/api/v1/payments", headers=write_headers(alpha_token, key), json=body
    )
    assert replayed.status_code == 201, replayed.text
    assert replayed.json() == paid.json(), "le rejeu rend la réponse initiale"

    written = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM payments WHERE id = :id",
        {"id": UUID(payment_id)},
    )
    assert written == 1
    still_partial = api_client.get(f"/api/v1/debts/{second_debt['id']}", headers=headers).json()
    assert Decimal(still_partial["balance"]) == Decimal("1000.00"), (
        "le rejeu n'a rien lettré une seconde fois"
    )

    # --- 4. une charge, et la dette fournisseur qui l'accompagne -------------
    category = api_client.post(
        "/api/v1/expense-categories",
        headers=headers,
        json={"name": f"Loyer {uuid4().hex[:8]}", "kind": "fixed"},
    )
    assert category.status_code == 201, category.text
    supplier = api_client.post(
        "/api/v1/suppliers", headers=headers, json={"name": f"Bailleur {uuid4().hex[:8]}"}
    )
    assert supplier.status_code == 201, supplier.text

    expense = api_client.post(
        "/api/v1/expenses",
        headers=write_headers(alpha_token),
        json={
            "category_id": str(category.json()["id"]),
            "supplier_id": str(supplier.json()["id"]),
            "label": "Loyer du mois",
            "amount": "800.00",
            "spent_at": today,
        },
    )
    assert expense.status_code == 201, expense.text
    assert expense.json()["expense_no"].startswith("D-")

    supplier_debt = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={
            "party_type": "supplier",
            "supplier_id": str(supplier.json()["id"]),
            "expense_id": expense.json()["id"],
            "principal": "800.00",
        },
    )
    assert supplier_debt.status_code == 201, supplier_debt.text

    # --- 5. l'état de l'argent sur la période --------------------------------
    # Le revenu de l'overview vient de `daily_sales_facts` (ADR 0034). En production
    # la tâche analytique le reconstruit après COMMIT ; ici, personne ne le fait.
    facts.rebuild_around(analytics_session_factory, session_factory, company_alpha.company_id)
    overview = api_client.get(
        f"/api/v1/analytics/overview?from={today}&to={today}", headers=headers
    )
    assert overview.status_code == 200, overview.text
    state = overview.json()

    # 5 unités vendues 1 000, rien de retourné.
    assert Decimal(state["net_revenue"]) >= Decimal("5000.00")
    # Encaissé 4 000, rien décaissé : la charge est constatée, pas encore payée.
    assert Decimal(state["cash_in"]) >= Decimal("4000.00")
    # Reste dû par le client : 1 000. Dû au fournisseur : 800.
    assert Decimal(state["receivables_open"]) >= Decimal("1000.00")
    assert Decimal(state["payables_open"]) >= Decimal("800.00")
    assert Decimal(state["fixed_expenses"]) >= Decimal("800.00")
    # Les deux identités du § 4.10 tiennent sur la réponse rendue.
    assert Decimal(state["gross_margin"]) == Decimal(state["net_revenue"]) - Decimal(
        state["cogs_net"]
    )
    assert Decimal(state["estimated_result"]) == Decimal(state["gross_margin"]) - Decimal(
        state["expenses_total"]
    )
