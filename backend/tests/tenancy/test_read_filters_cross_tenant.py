"""Les filtres de lecture ajoutés pour le frontend (ADR 0050) ne franchissent pas le tenant.

Un identifiant d'une autre entreprise passé en filtre ne doit rien révéler : la
réponse est vide, exactement comme pour un identifiant qui n'existe nulle part.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.events.inbox import Event
from app.core.events.types import EventType
from app.modules.inventory.events import stock_updated_payload
from app.workers.tasks.notifications import on_stock_updated
from tests.conftest import DemoCompany, auth_headers, write_headers

pytestmark = pytest.mark.tenancy


def _stocked_product(client: TestClient, token: str) -> str:
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"sku": f"XT-{marker}", "name": f"Article {marker}", "unit_price": "500.00"},
    )
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    stocked = client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={"product_id": product_id, "type": "initial", "qty_delta": "10", "unit_cost": "300"},
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def _customer_with_debt(client: TestClient, token: str, product_id: str) -> str:
    customer = client.post(
        "/api/v1/customers",
        headers=auth_headers(token),
        json={"name": f"Client {uuid4().hex[:8]}", "credit_limit": "100000"},
    )
    assert customer.status_code == 201, customer.text
    customer_id = str(customer.json()["id"])
    sale: dict[str, Any] = client.post(
        "/api/v1/sales", headers=auth_headers(token), json={"customer_id": customer_id}
    ).json()
    client.post(
        f"/api/v1/sales/{sale['id']}/items",
        headers=auth_headers(token),
        json={"product_id": product_id, "qty": "1"},
    )
    confirmed = client.post(
        f"/api/v1/sales/{sale['id']}/confirm",
        headers=write_headers(token),
        json={"paid_amount": "0", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return customer_id


def test_the_stock_filter_ignores_a_foreign_product(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    foreign = _stocked_product(api_client, beta_token)

    seen_by_alpha = api_client.get(
        f"/api/v1/inventory/stock?product_id={foreign}", headers=auth_headers(alpha_token)
    )
    assert seen_by_alpha.status_code == 200
    assert seen_by_alpha.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}

    # Le propriétaire, lui, voit bien sa ligne : le test ne passe pas à vide.
    seen_by_beta = api_client.get(
        f"/api/v1/inventory/stock?product_id={foreign}", headers=auth_headers(beta_token)
    )
    assert seen_by_beta.json()["total"] == 1


def test_the_debt_filter_ignores_a_foreign_customer(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    foreign = _customer_with_debt(api_client, beta_token, _stocked_product(api_client, beta_token))

    seen_by_alpha = api_client.get(
        f"/api/v1/debts?customer_id={foreign}", headers=auth_headers(alpha_token)
    )
    assert seen_by_alpha.status_code == 200
    assert seen_by_alpha.json()["total"] == 0

    seen_by_beta = api_client.get(
        f"/api/v1/debts?customer_id={foreign}", headers=auth_headers(beta_token)
    )
    assert seen_by_beta.json()["total"] == 1


def test_the_sale_customer_list_never_shows_another_company(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """`GET /sales/customer-choices` (ADR 0063) : ni en liste, ni en recherche, ni sa dette."""
    product_id = _stocked_product(api_client, beta_token)
    foreign = _customer_with_debt(api_client, beta_token, product_id)
    name = api_client.get(f"/api/v1/customers/{foreign}", headers=auth_headers(beta_token)).json()[
        "name"
    ]

    listed = api_client.get(
        "/api/v1/sales/customer-choices",
        headers=auth_headers(alpha_token),
        params={"page_size": 100},
    ).json()
    pages = [listed]
    for page in range(2, -(-listed["total"] // 100) + 1):
        pages.append(
            api_client.get(
                "/api/v1/sales/customer-choices",
                headers=auth_headers(alpha_token),
                params={"page_size": 100, "page": page},
            ).json()
        )
    assert foreign not in {item["id"] for body in pages for item in body["items"]}

    searched = api_client.get(
        "/api/v1/sales/customer-choices",
        headers=auth_headers(alpha_token),
        params={"search": name},
    ).json()
    assert foreign not in {item["id"] for item in searched["items"]}

    # Le propriétaire, lui, le voit avec sa dette : le test ne passe pas à vide.
    own = api_client.get(
        "/api/v1/sales/customer-choices",
        headers=auth_headers(beta_token),
        params={"search": name},
    ).json()
    mine = [item for item in own["items"] if item["id"] == foreign]
    assert mine and mine[0]["open_debt"] != "0.00"


def test_the_sales_search_by_name_never_finds_another_company(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """`GET /sales?search=` (ADR 0070) cherche les clients du tenant, jamais ceux d'autrui.

    Le nom est rare : la recherche par trigrammes trouverait sinon, chez alpha, ses
    propres clients au nom voisin (« Client … »), ce qui n'est pas une fuite.
    """
    product_id = _stocked_product(api_client, beta_token)
    name = f"Zéphyrine Kouyaté {uuid4().hex[:6]}"
    customer = api_client.post(
        "/api/v1/customers", headers=auth_headers(beta_token), json={"name": name}
    )
    assert customer.status_code == 201, customer.text
    sale: dict[str, Any] = api_client.post(
        "/api/v1/sales",
        headers=auth_headers(beta_token),
        json={"customer_id": customer.json()["id"]},
    ).json()
    api_client.post(
        f"/api/v1/sales/{sale['id']}/items",
        headers=auth_headers(beta_token),
        json={"product_id": product_id, "qty": "1"},
    )
    confirmed = api_client.post(
        f"/api/v1/sales/{sale['id']}/confirm",
        headers=write_headers(beta_token),
        json={"paid_amount": "500", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    seen_by_alpha = api_client.get(
        "/api/v1/sales", headers=auth_headers(alpha_token), params={"search": name}
    )
    assert seen_by_alpha.status_code == 200
    assert sale["id"] not in {item["id"] for item in seen_by_alpha.json()["items"]}

    seen_by_beta = api_client.get(
        "/api/v1/sales", headers=auth_headers(beta_token), params={"search": name}
    )
    assert sale["id"] in {item["id"] for item in seen_by_beta.json()["items"]}


def test_day_totals_count_only_the_readers_sales(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """`GET /sales/day-totals` (ADR 0070) : une vente de beta ne change rien chez alpha."""
    window = {"date_from": "2000-01-01T00:00:00Z", "date_to": "2100-01-01T00:00:00Z"}

    def counts(token: str) -> int:
        response = api_client.get(
            "/api/v1/sales/day-totals", headers=auth_headers(token), params=window
        )
        assert response.status_code == 200, response.text
        return sum(item["sale_count"] for item in response.json()["items"])

    alpha_before, beta_before = counts(alpha_token), counts(beta_token)
    _customer_with_debt(api_client, beta_token, _stocked_product(api_client, beta_token))
    assert counts(alpha_token) == alpha_before
    assert counts(beta_token) == beta_before + 1


def test_the_stock_list_and_summary_never_show_another_company(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """`GET /inventory/stock?search=` et le résumé (ADR 0071) restent dans le tenant."""
    foreign = _stocked_product(api_client, beta_token)
    name = api_client.get(f"/api/v1/products/{foreign}", headers=auth_headers(beta_token)).json()[
        "name"
    ]
    seen = api_client.get(
        "/api/v1/inventory/stock",
        headers=auth_headers(alpha_token),
        params={"search": name, "page_size": 100},
    ).json()
    assert foreign not in {item["product_id"] for item in seen["items"]}
    own = api_client.get(
        "/api/v1/inventory/stock",
        headers=auth_headers(beta_token),
        params={"search": name, "page_size": 100},
    ).json()
    assert foreign in {item["product_id"] for item in own["items"]}

    before = api_client.get(
        "/api/v1/inventory/stock/summary", headers=auth_headers(alpha_token)
    ).json()
    _stocked_product(api_client, beta_token)
    after = api_client.get(
        "/api/v1/inventory/stock/summary", headers=auth_headers(alpha_token)
    ).json()
    assert after["product_count"] == before["product_count"]


def test_a_delivery_of_another_company_s_article_is_refused(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """Article de beta livré chez alpha : 404, et ni dette ni mouvement ne restent."""
    foreign = _stocked_product(api_client, beta_token)
    supplier = api_client.post(
        "/api/v1/suppliers",
        headers=auth_headers(alpha_token),
        json={"name": f"Fournisseur {uuid4().hex[:8]}"},
    ).json()["id"]
    refused = api_client.post(
        "/api/v1/inventory/deliveries",
        headers=write_headers(alpha_token),
        json={
            "supplier_id": supplier,
            "lines": [{"product_id": foreign, "qty": "5", "unit_cost": "100"}],
            "payment_mode": "later",
        },
    )
    assert refused.status_code == 404, refused.text
    debts = api_client.get(
        "/api/v1/debts",
        headers=auth_headers(alpha_token),
        params={"party_type": "supplier", "supplier_id": supplier},
    ).json()
    assert debts["total"] == 0


def test_the_people_lists_never_show_another_company(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """Listes des écrans 13 (ADR 0072) : ni la personne, ni sa dette, ni son téléphone."""
    product = _stocked_product(api_client, beta_token)
    foreign = _customer_with_debt(api_client, beta_token, product)
    phone = f"77 {uuid4().int % 1000:03d} {uuid4().int % 100:02d} 11"
    api_client.patch(
        f"/api/v1/customers/{foreign}", headers=auth_headers(beta_token), json={"phone": phone}
    )
    supplier = api_client.post(
        "/api/v1/suppliers", headers=auth_headers(beta_token), json={"name": "Grossiste Bêta"}
    ).json()["id"]
    for kind, search, person in (
        ("customers", phone, foreign),
        ("customers", None, foreign),
        ("suppliers", "Grossiste Bêta", supplier),
    ):
        params: dict[str, Any] = {"page_size": 100}
        if search:
            params["search"] = search
        own = api_client.get(
            f"/api/v1/analytics/{kind}", headers=auth_headers(beta_token), params=params
        ).json()
        assert person in {row["id"] for row in own["items"]}
        seen = api_client.get(
            f"/api/v1/analytics/{kind}", headers=auth_headers(alpha_token), params=params
        ).json()
        assert person not in {row["id"] for row in seen["items"]}
    owing = api_client.get(
        "/api/v1/analytics/customers",
        headers=auth_headers(alpha_token),
        params={"owing": "true", "page_size": 100},
    ).json()
    assert foreign not in {row["id"] for row in owing["items"]}


def test_the_money_screens_never_show_another_company(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """Écrans 17, 20 et 21 (ADR 0073) : ni la dette, ni la ligne de caisse, ni la dépense."""
    product = _stocked_product(api_client, beta_token)
    foreign = _customer_with_debt(api_client, beta_token, product)
    category = api_client.post(
        "/api/v1/expense-categories",
        headers=auth_headers(beta_token),
        json={"name": f"Loyer {uuid4().hex[:8]}", "kind": "fixed"},
    ).json()["id"]
    today = api_client.get("/api/v1/analytics/cash", headers=auth_headers(beta_token)).json()["day"]
    expense = api_client.post(
        "/api/v1/expenses",
        headers=write_headers(beta_token),
        json={
            "category_id": category,
            "label": "Loyer de la boutique bêta",
            "amount": "987654",
            "spent_at": today,
            "payment": {"method": "cash"},
        },
    )
    assert expense.status_code == 201, expense.text

    def read(token: str, path: str, **params: str) -> dict[str, Any]:
        response = api_client.get(f"/api/v1{path}", headers=auth_headers(token), params=params)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    own_cash = read(beta_token, "/analytics/cash")
    beta_payments = {line["payment_id"] for line in own_cash["lines"]}
    assert beta_payments
    seen_cash = read(alpha_token, "/analytics/cash")
    assert not beta_payments & {line["payment_id"] for line in seen_cash["lines"]}

    own_month = read(beta_token, "/analytics/money", period="month")
    assert foreign in {row["id"] for row in own_month["receivables"]["rows"]} or (
        own_month["receivables"]["count"] > 3
    )
    seen_month = read(alpha_token, "/analytics/money", period="month")
    assert foreign not in {row["id"] for row in seen_month["receivables"]["rows"]}
    assert (seen_month["biggest_expense"] or {}).get("label") != "Loyer de la boutique bêta"

    assert category in {
        row["category_id"] for row in read(beta_token, "/analytics/expenses-summary")["by_category"]
    }
    seen = read(alpha_token, "/analytics/expenses-summary")
    assert category not in {row["category_id"] for row in seen["by_category"]}
    assert "Loyer de la boutique bêta" not in {row["label"] for row in seen["recent"]}


def test_mark_all_read_never_reaches_another_company(
    api_client: TestClient, alpha_token: str, beta_token: str, company_beta: DemoCompany
) -> None:
    """« Tout marquer comme lu » (ADR 0074) : le fil d'une autre entreprise reste intact."""
    product = _stocked_product(api_client, beta_token)
    on_stock_updated(
        **Event(
            id=990_000_000 + uuid4().int % 1_000_000,
            company_id=company_beta.company_id,
            event_type=EventType.STOCK_UPDATED,
            aggregate_type="product",
            aggregate_id=UUID(product),
            payload=stock_updated_payload(
                product_id=UUID(product),
                qty_on_hand=Decimal("0"),
                avg_cost=Decimal("300.0000"),
                movement_id=uuid4(),
                below_reorder_point=True,
            ),
            occurred_at=datetime.now(UTC),
        ).as_message()
    )
    before = api_client.get(
        "/api/v1/notifications/unread-count", headers=auth_headers(beta_token)
    ).json()["unread"]
    assert before > 0
    done = api_client.post("/api/v1/notifications/read-all", headers=auth_headers(alpha_token))
    assert done.status_code == 200, done.text
    after = api_client.get(
        "/api/v1/notifications/unread-count", headers=auth_headers(beta_token)
    ).json()["unread"]
    assert after == before
