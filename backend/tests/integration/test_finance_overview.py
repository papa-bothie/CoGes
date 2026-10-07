"""« Où en est mon argent ? » — l'overview, vérifié chiffre par chiffre.

Les mesures sont celles du § 4.10, reprises à la lettre pour que la phase 08 puisse
basculer sur `daily_sales_facts` sans changer un seul résultat :

    net_revenue = gross_revenue − discount_total − refund_net_amount
    cogs_net    = cogs_gross − cogs_returned
    marge       = net_revenue − cogs_net
    résultat    = marge − dépenses de la période

Deux propriétés méritent leur propre test : la trésorerie **exclut** les écritures
de compensation (`method = 'offset'`, ADR 0024), et les retours sont rattachés au
jour de la **vente d'origine**, pas au leur.

Depuis la phase 08, le revenu et le coût des ventes viennent de `daily_sales_facts`
et non plus de `sale_items` (ADR 0034) : l'overview est **éventuellement cohérent**.
Aucun worker ne tourne pendant la suite, donc chaque test qui mesure un revenu
reconstruit d'abord les faits du jour, comme le fait la tâche analytique après COMMIT.
Les tests qui ne portent que sur la trésorerie ou les encours n'en ont pas besoin :
ces mesures-là restent lues sur le transactionnel.
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
    TEST_PASSWORD,
    DemoCompany,
    auth_headers,
    read_scalar_in_tenant,
    write_headers,
)
from tests.integration import facts_harness as facts

pytestmark = pytest.mark.integration

OVERVIEW = "/api/v1/analytics/overview"


def _today_range() -> str:
    today = date.today().isoformat()
    return f"from={today}&to={today}"


def _product(client: TestClient, token: str, *, unit_price: str, unit_cost: str) -> str:
    """Un produit non taxé, garni de 100 unités au coût demandé.

    Sans taxe : l'overview mesure des montants **hors taxe**, et une TVA de 18 %
    ajouterait au test une arithmétique qui ne prouve rien de plus.
    """
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={
            "sku": f"SKU-{marker}",
            "name": f"Produit {marker}",
            "unit_price": unit_price,
            "default_tax_rate": "0",
        },
    )
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])

    stocked = client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={
            "product_id": product_id,
            "type": "initial",
            "qty_delta": "100",
            "unit_cost": unit_cost,
        },
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def _confirmed_sale(
    client: TestClient, token: str, product_id: str, *, qty: str, paid: str
) -> dict[str, Any]:
    sale = client.post("/api/v1/sales", headers=auth_headers(token), json={})
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
        json={"paid_amount": paid, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body: dict[str, Any] = confirmed.json()
    body["sale_item_id"] = str(line.json()["id"])
    return body


def _overview(client: TestClient, token: str, query: str | None = None) -> dict[str, Any]:
    response = client.get(f"{OVERVIEW}?{query or _today_range()}", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_the_overview_adds_up_revenue_cost_margin_and_expenses(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> None:
    """Une vente, une charge : marge et résultat estimé se recalculent à la main.

    2 unités vendues 1 000 au coût de 600 ⇒ CA net 2 000, coût 1 200, marge 800.
    Une charge de 300 ⇒ résultat estimé 500.
    """
    facts.rebuild_around(analytics_session_factory, session_factory, company_alpha.company_id)
    before = _overview(api_client, alpha_token)
    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    _confirmed_sale(api_client, alpha_token, product_id, qty="2", paid="2000.00")

    category = api_client.post(
        "/api/v1/expense-categories",
        headers=auth_headers(alpha_token),
        json={"name": f"Charge {uuid4().hex[:8]}", "kind": "variable"},
    )
    assert category.status_code == 201, category.text
    expense = api_client.post(
        "/api/v1/expenses",
        headers=write_headers(alpha_token),
        json={
            "category_id": str(category.json()["id"]),
            "label": "Transport",
            "amount": "300.00",
            "spent_at": date.today().isoformat(),
        },
    )
    assert expense.status_code == 201, expense.text

    facts.rebuild_around(analytics_session_factory, session_factory, company_alpha.company_id)
    after = _overview(api_client, alpha_token)
    delta = {
        key: Decimal(after[key]) - Decimal(before[key])
        for key in (
            "gross_revenue",
            "net_revenue",
            "cogs_net",
            "gross_margin",
            "expenses_total",
            "variable_expenses",
            "estimated_result",
            "cash_in",
        )
    }
    assert delta["gross_revenue"] == Decimal("2000.00")
    assert delta["net_revenue"] == Decimal("2000.00")
    assert delta["cogs_net"] == Decimal("1200.00")
    assert delta["gross_margin"] == Decimal("800.00")
    assert delta["expenses_total"] == Decimal("300.00")
    assert delta["variable_expenses"] == Decimal("300.00")
    assert delta["estimated_result"] == Decimal("500.00")
    assert delta["cash_in"] == Decimal("2000.00")

    # L'identité que le § 4.10 pose, vérifiée sur la réponse elle-même.
    assert Decimal(after["gross_margin"]) == Decimal(after["net_revenue"]) - Decimal(
        after["cogs_net"]
    )
    assert Decimal(after["estimated_result"]) == Decimal(after["gross_margin"]) - Decimal(
        after["expenses_total"]
    )


def test_a_return_reduces_the_revenue_and_the_cost_of_its_sale(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> None:
    """Le retour compense exactement ce que la vente avait produit.

    C'est la propriété que le § 5.3 protège en faisant revenir la marchandise **au
    coût auquel elle est sortie** : rendre la moitié d'une vente retire la moitié
    du revenu et la moitié du coût, donc la moitié de la marge. Ni plus, ni moins.
    """
    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    sale = _confirmed_sale(api_client, alpha_token, product_id, qty="4", paid="4000.00")
    facts.rebuild_around(analytics_session_factory, session_factory, company_alpha.company_id)
    before = _overview(api_client, alpha_token)

    returned = api_client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=write_headers(alpha_token),
        json={"lines": [{"sale_item_id": sale["sale_item_id"], "qty": "2"}]},
    )
    assert returned.status_code == 201, returned.text

    # Le retour est rattaché au jour de la **vente d'origine** (§ 4.10) : c'est ce
    # jour-là qu'il faut réécrire, et c'est aujourd'hui puisque la vente est du jour.
    facts.rebuild_around(analytics_session_factory, session_factory, company_alpha.company_id)
    after = _overview(api_client, alpha_token)
    assert Decimal(after["refund_net_amount"]) - Decimal(before["refund_net_amount"]) == Decimal(
        "2000.00"
    )
    assert Decimal(before["net_revenue"]) - Decimal(after["net_revenue"]) == Decimal("2000.00")
    assert Decimal(before["cogs_net"]) - Decimal(after["cogs_net"]) == Decimal("1200.00")
    assert Decimal(before["gross_margin"]) - Decimal(after["gross_margin"]) == Decimal("800.00")


def test_a_compensation_never_appears_in_the_treasury(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Deux écritures `offset`, zéro mouvement de caisse (ADR 0024).

    Un client à crédit rapporte sa marchandise : sa dette baisse, le retour est
    réglé, et **aucun argent ne bouge**. La trésorerie ne doit donc pas bouger non
    plus — c'est exactement la dette que l'ADR 0024 laissait à cette phase.
    """
    customer = api_client.post(
        "/api/v1/customers",
        headers=auth_headers(alpha_token),
        json={"name": f"Client {uuid4().hex[:8]}"},
    )
    assert customer.status_code == 201, customer.text
    customer_id = str(customer.json()["id"])

    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    sale = api_client.post(
        "/api/v1/sales", headers=auth_headers(alpha_token), json={"customer_id": customer_id}
    )
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])
    line = api_client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(alpha_token),
        json={"product_id": product_id, "qty": "2"},
    )
    assert line.status_code == 201, line.text
    # Vente entièrement à crédit : la dette vaut 2 000.
    confirmed = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(alpha_token),
        json={"paid_amount": "0", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    returned = api_client.post(
        f"/api/v1/sales/{sale_id}/returns",
        headers=write_headers(alpha_token),
        json={"lines": [{"sale_item_id": str(line.json()["id"]), "qty": "1"}]},
    )
    assert returned.status_code == 201, returned.text
    return_id = str(returned.json()["id"])

    before = _overview(api_client, alpha_token)
    compensated = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=write_headers(alpha_token),
        json={"amount": "1000.00", "method": "offset"},
    )
    assert compensated.status_code == 200, compensated.text

    after = _overview(api_client, alpha_token)
    assert after["cash_in"] == before["cash_in"], "aucune entrée de caisse"
    assert after["cash_out"] == before["cash_out"], "aucune sortie de caisse"

    # Les deux paiements `offset` existent pourtant bien : c'est leur méthode,
    # et elle seule, qui les tient hors de la trésorerie.
    written = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM payments WHERE method = 'offset'",
    )
    assert written >= 2


#: Un paiement annulé et sa contre-écriture sortent tous deux de la trésorerie (ADR 0038).
_LIVE_CASH = (
    "p.reversal_of_payment_id IS NULL AND NOT EXISTS (SELECT 1 FROM payments r"
    " WHERE r.company_id = p.company_id AND r.reversal_of_payment_id = p.id)"
)


def test_the_treasury_matches_the_sum_of_real_payments(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Le solde de la période est la somme des versements, sans exception cachée."""
    api_client.post(
        "/api/v1/payments",
        headers=write_headers(alpha_token),
        json={"direction": "inflow", "method": "cash", "amount": "1234.00"},
    )
    api_client.post(
        "/api/v1/payments",
        headers=write_headers(alpha_token),
        json={"direction": "outflow", "method": "cash", "amount": "234.00"},
    )

    body = _overview(api_client, alpha_token)
    today = date.today()
    expected_in = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT coalesce(sum(amount), 0) FROM payments p "
        " WHERE method <> 'offset' AND direction = 'inflow' AND paid_at::date = :day"
        f" AND {_LIVE_CASH}",
        {"day": today},
    )
    expected_out = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT coalesce(sum(amount), 0) FROM payments p "
        " WHERE method <> 'offset' AND direction = 'outflow' AND paid_at::date = :day"
        f" AND {_LIVE_CASH}",
        {"day": today},
    )
    assert Decimal(body["cash_in"]) == expected_in
    assert Decimal(body["cash_out"]) == expected_out
    assert Decimal(body["net_cash"]) == expected_in - expected_out


def test_open_debts_are_reported_in_both_directions(
    api_client: TestClient, alpha_token: str
) -> None:
    """Créances et dettes fournisseurs ne se compensent jamais l'une l'autre."""
    before = _overview(api_client, alpha_token)
    customer = api_client.post(
        "/api/v1/customers",
        headers=auth_headers(alpha_token),
        json={"name": f"Client {uuid4().hex[:8]}"},
    )
    supplier = api_client.post(
        "/api/v1/suppliers",
        headers=auth_headers(alpha_token),
        json={"name": f"Fournisseur {uuid4().hex[:8]}"},
    )
    api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={
            "party_type": "customer",
            "customer_id": str(customer.json()["id"]),
            "principal": "700.00",
        },
    )
    api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={
            "party_type": "supplier",
            "supplier_id": str(supplier.json()["id"]),
            "principal": "1100.00",
        },
    )

    after = _overview(api_client, alpha_token)
    assert Decimal(after["receivables_open"]) - Decimal(before["receivables_open"]) == Decimal(
        "700.00"
    )
    assert Decimal(after["payables_open"]) - Decimal(before["payables_open"]) == Decimal("1100.00")


def test_the_daily_series_covers_thirty_days_without_holes(
    api_client: TestClient, alpha_token: str
) -> None:
    """Trente points, jours creux compris : une courbe trouée se lirait comme une
    absence de données, pas comme une caisse immobile."""
    end = date.today()
    start = end - timedelta(days=59)
    body = _overview(api_client, alpha_token, f"from={start.isoformat()}&to={end.isoformat()}")

    days = [point["day"] for point in body["daily"]]
    assert len(days) == 30, days
    assert days == sorted(days), "la série est chronologique"
    assert days[-1] == end.isoformat()
    for point in body["daily"]:
        assert Decimal(point["net_cash"]) == Decimal(point["cash_in"]) - Decimal(point["cash_out"])


def test_the_period_is_mandatory_and_bounded(api_client: TestClient, alpha_token: str) -> None:
    """Pas d'agrégat sur « tout l'historique », et pas de plage à l'envers."""
    missing = api_client.get(OVERVIEW, headers=auth_headers(alpha_token))
    assert missing.status_code == 422, missing.text

    inverted = api_client.get(
        f"{OVERVIEW}?from=2026-06-30&to=2026-06-01", headers=auth_headers(alpha_token)
    )
    assert inverted.status_code == 422, inverted.text
    assert inverted.json()["error"]["code"] == "period_inverted"

    too_long = api_client.get(
        f"{OVERVIEW}?from=2020-01-01&to=2026-12-31", headers=auth_headers(alpha_token)
    )
    assert too_long.status_code == 422, too_long.text
    assert too_long.json()["error"]["code"] == "period_too_long"


def test_a_seller_cannot_read_the_margin(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """`analytics:read`, et non `dashboard:read` : une caisse encaisse, elle ne
    lit pas la marge de l'entreprise."""
    role = api_client.get("/api/v1/roles?page_size=50", headers=auth_headers(alpha_token))
    role_id = str(next(item["id"] for item in role.json()["items"] if item["name"] == "vendeur"))
    email = f"vendeur-{uuid4().hex[:8]}@{company_alpha.slug}.example.com"
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(alpha_token),
        json={
            "email": email,
            "full_name": "Caissier",
            "password": TEST_PASSWORD,
            "role_ids": [role_id],
        },
    )
    assert created.status_code == 201, created.text
    login = api_client.post(
        "/api/v1/auth/login",
        json={"company_slug": company_alpha.slug, "email": email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text

    refused = api_client.get(
        f"{OVERVIEW}?{_today_range()}", headers=auth_headers(login.json()["access_token"])
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["required_permission"] == "analytics:read"
