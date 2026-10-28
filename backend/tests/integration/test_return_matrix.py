"""Matrice des retours (prompt 28, C1, ADR 0097) : une vente confirmée se retourne, quel
que soit son état de paiement.

Chaque case répond aux quatre questions du propriétaire : le retour s'enregistre-t-il ?
le stock rentre-t-il ? la dette est-elle déduite d'abord ? le remboursement passe-t-il ?
Les tests passent par l'API : c'est le contrat que l'écran consomme. Les garanties
structurelles restent à T18-T22, qui attaquent la base.
"""

from __future__ import annotations

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

pytestmark = pytest.mark.integration

# Une ligne de 10 unités à 1 000 F + 18 % : 11 800 F ; 1 unité rendue vaut 1 180 F.
UNIT = Decimal("1180.00")
TOTAL = Decimal("11800.00")


# ----------------------------------------------------------------- utilitaires


def _role_id(client: TestClient, token: str, name: str) -> str:
    response = client.get("/api/v1/roles?page_size=50", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return str(next(role["id"] for role in response.json()["items"] if role["name"] == name))


def _token_for_role(client: TestClient, token: str, company: DemoCompany, role: str) -> str:
    if role == "gerant":
        return token
    email = f"{role}-{uuid4().hex[:8]}@{company.slug}.example.com"
    created = client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={
            "email": email,
            "full_name": f"Compte {role}",
            "password": TEST_PASSWORD,
            "role_ids": [_role_id(client, token, role)],
        },
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login",
        json={"company_slug": company.slug, "email": email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


def _product(client: TestClient, token: str, *, tracked: bool = True, stock: str = "100") -> str:
    marker = uuid4().hex[:8]
    body: dict[str, Any] = {
        "sku": f"SKU-{marker}",
        "name": f"Article {marker}",
        "unit_price": "1000.00",
        "default_tax_rate": "0.1800",
    }
    if not tracked:
        body["is_stock_tracked"] = False
    created = client.post("/api/v1/products", headers=auth_headers(token), json=body)
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    if tracked:
        stocked = client.post(
            "/api/v1/inventory/movements",
            headers=auth_headers(token),
            json={
                "product_id": product_id,
                "type": "initial",
                "qty_delta": stock,
                "unit_cost": "600",
            },
        )
        assert stocked.status_code == 201, stocked.text
    return product_id


def _customer(client: TestClient, token: str) -> str:
    created = client.post(
        "/api/v1/customers", headers=auth_headers(token), json={"name": f"Client {uuid4().hex[:8]}"}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _sale(
    client: TestClient,
    token: str,
    product_id: str,
    *,
    paid: Decimal,
    method: str = "cash",
    customer_id: str | None = None,
) -> tuple[str, str]:
    headers = auth_headers(token)
    sale = client.post(
        "/api/v1/sales",
        headers=headers,
        json={} if customer_id is None else {"customer_id": customer_id},
    )
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])
    item = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=headers,
        json={"product_id": product_id, "qty": "10"},
    )
    assert item.status_code == 201, item.text
    confirmed = client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(token),
        json={"paid_amount": str(paid), "method": method},
    )
    assert confirmed.status_code == 200, confirmed.text
    return sale_id, str(confirmed.json()["items"][0]["id"])


def _stock(client: TestClient, token: str, product_id: str) -> Decimal:
    response = client.get(
        "/api/v1/inventory/stock",
        params={"product_id": product_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    items = [i for i in response.json()["items"] if i["product_id"] == product_id]
    return Decimal(items[0]["qty_on_hand"]) if items else Decimal("0")


def _return(
    client: TestClient, token: str, sale_id: str, item_id: str, qty: str, **extra: Any
) -> Any:
    return client.post(
        f"/api/v1/sales/{sale_id}/returns",
        headers=write_headers(token),
        json={"lines": [{"sale_item_id": item_id, "qty": qty}], **extra},
    )


def _refund(client: TestClient, token: str, return_id: str, amount: Decimal, method: str) -> Any:
    return client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=write_headers(token),
        json={"amount": str(amount), "method": method},
    )


def _debt_balance(client: TestClient, token: str, sale_id: str) -> Decimal | None:
    debt = client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(token)).json()["debt"]
    return None if debt is None else Decimal(debt["balance"])


# ------------------------------------------------------------ la matrice


# (nom, payé à la confirmation, moyen, client identifié, dette abandonnée)
PAYMENTS = [
    ("payée en espèces", TOTAL, "cash", False, False),
    ("payée en mobile money", TOTAL, "wave", False, False),
    ("payée, client identifié", TOTAL, "cash", True, False),
    ("partiellement payée", Decimal("5000.00"), "cash", True, False),
    ("à crédit non payée", Decimal("0"), "cash", True, False),
    ("dette passée en perte", Decimal("3000.00"), "cash", True, True),
]


@pytest.mark.parametrize("role", ["gerant", "vendeur"])
@pytest.mark.parametrize(("case", "paid", "method", "identified", "written_off"), PAYMENTS)
@pytest.mark.parametrize("qty", ["3", "10"], ids=["partiel", "total"])
def test_a_confirmed_sale_is_returned_whatever_its_payment(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    role: str,
    case: str,
    paid: Decimal,
    method: str,
    identified: bool,
    written_off: bool,
    qty: str,
) -> None:
    """Retour, stock, dette déduite d'abord, puis le surplus selon le rôle."""
    token = _token_for_role(api_client, alpha_token, company_alpha, role)
    product_id = _product(api_client, alpha_token)
    customer_id = _customer(api_client, alpha_token) if identified else None
    sale_id, item_id = _sale(
        api_client, alpha_token, product_id, paid=paid, method=method, customer_id=customer_id
    )
    debt_id = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token)).json()[
        "debt"
    ]
    if written_off:
        off = api_client.post(
            f"/api/v1/debts/{debt_id['id']}/write-off",
            headers=write_headers(alpha_token),
            json={"reason": "Client parti"},
        )
        assert off.status_code == 200, off.text
    stock_before = _stock(api_client, alpha_token, product_id)
    debt_before = _debt_balance(api_client, alpha_token, sale_id)
    open_debt = Decimal("0") if written_off or debt_before is None else debt_before

    created = _return(api_client, token, sale_id, item_id, qty, offset_debt=True)
    assert created.status_code == 201, f"{case} / {role} : {created.text}"
    body = created.json()
    value = UNIT * Decimal(qty)
    assert Decimal(body["total_refund"]) == value
    assert _stock(api_client, alpha_token, product_id) == stock_before + Decimal(qty)

    # La dette restante est déduite d'abord, par le vendeur comme par le gérant.
    offset = min(value, open_debt)
    assert Decimal(body["refund_due"]) == value - offset, case
    if debt_before is not None and not written_off:
        assert _debt_balance(api_client, alpha_token, sale_id) == debt_before - offset

    surplus = value - offset
    if surplus == 0:
        assert body["refund_status"] == "settled"
        return

    # Ce qui reste se rend en argent, au plus ce que le client a réellement versé.
    cash_cap = paid  # aucun remboursement antérieur sur ces ventes neuves
    refund = _refund(api_client, token, body["id"], surplus, "wave")
    if role == "vendeur":
        assert refund.status_code == 403, refund.text
        assert body["refund_status"] in {"pending", "partial"}
        return
    if surplus > cash_cap:
        assert refund.status_code == 409, refund.text
        assert refund.json()["error"]["code"] == "refund_exceeds_paid"
        accepted = _refund(api_client, token, body["id"], cash_cap, "cash")
        assert accepted.status_code == 200, accepted.text
        return
    assert refund.status_code == 200, f"{case} : {refund.text}"
    assert refund.json()["refund_status"] == "settled"


@pytest.mark.parametrize("article", ["non suivi", "supprimé depuis la vente"])
def test_any_article_of_a_confirmed_sale_is_returned(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    article: str,
) -> None:
    tracked = article != "non suivi"
    product_id = _product(api_client, alpha_token, tracked=tracked, stock="10")
    sale_id, item_id = _sale(api_client, alpha_token, product_id, paid=TOTAL)
    if article == "supprimé depuis la vente":
        deleted = api_client.delete(
            f"/api/v1/products/{product_id}", headers=auth_headers(alpha_token)
        )
        assert deleted.status_code == 200, deleted.text

    created = _return(api_client, alpha_token, sale_id, item_id, "3", offset_debt=True)
    assert created.status_code == 201, created.text
    refund = _refund(api_client, alpha_token, created.json()["id"], UNIT * 3, "cash")
    assert refund.status_code == 200, refund.text
    if tracked:
        # Lu en base : la liste du stock n'affiche plus un article supprimé.
        on_hand = read_scalar_in_tenant(
            session_factory,
            company_alpha.company_id,
            "SELECT qty_on_hand FROM product_stock WHERE product_id = :product_id",
            {"product_id": product_id},
        )
        assert on_hand == Decimal("3")


def test_a_second_return_takes_the_remaining_quantities(
    api_client: TestClient, alpha_token: str
) -> None:
    product_id = _product(api_client, alpha_token)
    customer_id = _customer(api_client, alpha_token)
    sale_id, item_id = _sale(
        api_client, alpha_token, product_id, paid=Decimal("5000.00"), customer_id=customer_id
    )
    first = _return(api_client, alpha_token, sale_id, item_id, "3", offset_debt=True)
    assert first.status_code == 201, first.text
    second = _return(api_client, alpha_token, sale_id, item_id, "7", offset_debt=True)
    assert second.status_code == 201, second.text
    # Dette de 6 800 F : 3 540 déduits au premier, 3 260 au second ; 5 000 F à rendre.
    assert Decimal(second.json()["refund_due"]) == UNIT * 7 - Decimal("3260.00")
    assert _debt_balance(api_client, alpha_token, sale_id) == Decimal("0.00")
    too_much = _return(api_client, alpha_token, sale_id, item_id, "1", offset_debt=True)
    assert too_much.status_code == 409


def test_the_accountant_neither_records_nor_refunds_a_return(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    accountant = _token_for_role(api_client, alpha_token, company_alpha, "comptable")
    product_id = _product(api_client, alpha_token)
    sale_id, item_id = _sale(api_client, alpha_token, product_id, paid=TOTAL)
    refused = _return(api_client, accountant, sale_id, item_id, "1", offset_debt=True)
    assert refused.status_code == 403
    created = _return(api_client, alpha_token, sale_id, item_id, "1")
    assert _refund(api_client, accountant, created.json()["id"], UNIT, "cash").status_code == 403


def test_without_offset_debt_the_return_leaves_the_debt_alone(
    api_client: TestClient, alpha_token: str
) -> None:
    """Sans `offset_debt`, rien ne change (ADR 0024, 0025) : la dette attend le gérant."""
    product_id = _product(api_client, alpha_token)
    customer_id = _customer(api_client, alpha_token)
    sale_id, item_id = _sale(
        api_client, alpha_token, product_id, paid=Decimal("0"), customer_id=customer_id
    )
    created = _return(api_client, alpha_token, sale_id, item_id, "3")
    assert created.status_code == 201, created.text
    assert Decimal(created.json()["refund_due"]) == UNIT * 3
    assert _debt_balance(api_client, alpha_token, sale_id) == TOTAL


def test_the_list_offers_a_return_for_the_same_sales_as_their_page(
    api_client: TestClient, alpha_token: str
) -> None:
    """« Retour » dans l'historique : tant qu'une ligne n'est pas entièrement rendue."""
    headers = auth_headers(alpha_token)
    product_id = _product(api_client, alpha_token)
    sale_id, item_id = _sale(api_client, alpha_token, product_id, paid=TOTAL)

    def listed() -> bool:
        page = api_client.get("/api/v1/sales?page_size=100", headers=headers).json()
        return bool(next(sale for sale in page["items"] if sale["id"] == sale_id)["returnable"])

    assert listed() is True
    assert _return(api_client, alpha_token, sale_id, item_id, "4").status_code == 201
    assert listed() is True
    detail = api_client.get(f"/api/v1/sales/{sale_id}", headers=headers).json()
    assert detail["returnable"] is True
    assert _return(api_client, alpha_token, sale_id, item_id, "6").status_code == 201
    assert listed() is False

    draft = api_client.post("/api/v1/sales", headers=headers, json={}).json()
    page = api_client.get("/api/v1/sales?status=draft&page_size=100", headers=headers).json()
    assert next(s for s in page["items"] if s["id"] == draft["id"])["returnable"] is False
