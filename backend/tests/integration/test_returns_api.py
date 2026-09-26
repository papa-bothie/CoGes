"""Retours et remboursements vus par l'API : le contrat rendu au client.

Ces tests passent **volontairement** par l'API. Ils ne mesurent pas les garanties
structurelles — c'est le rôle de T18 à T22, qui attaquent la base — mais ce que le
gérant obtient : un remboursable juste, un stock rentré au bon coût, des refus
nommés, et une compensation qui ne fait bouger aucune caisse.
"""

from __future__ import annotations

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


# ----------------------------------------------------------------- utilitaires


def _role_id(client: TestClient, token: str, name: str) -> str:
    response = client.get("/api/v1/roles?page_size=50", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return str(next(role["id"] for role in response.json()["items"] if role["name"] == name))


def _token_for_role(client: TestClient, token: str, company: DemoCompany, role: str) -> str:
    """Compte porteur d'un rôle système, et son jeton d'accès."""
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
    access_token: str = login.json()["access_token"]
    return access_token


def _product(client: TestClient, token: str, *, unit_price: str = "1000.00") -> str:
    """Un produit neuf, taxé à 18 %, avec 100 unités au coût de 600."""
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={
            "sku": f"SKU-{marker}",
            "name": f"Article {marker}",
            "unit_price": unit_price,
            "default_tax_rate": "0.1800",
        },
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


def _customer(client: TestClient, token: str) -> str:
    created = client.post(
        "/api/v1/customers",
        headers=auth_headers(token),
        json={"name": f"Client {uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _confirmed_sale(
    client: TestClient,
    token: str,
    product_id: str,
    *,
    qty: str = "10",
    paid: str | None = None,
    customer_id: str | None = None,
    discount: str = "0",
) -> tuple[str, str, dict[str, Any]]:
    """Une vente confirmée d'une ligne. Rend `(sale_id, sale_item_id, corps)`.

    `paid = None` signifie « payée intégralement » : sans client identifié, le solde
    ouvrirait une dette que `customer_required_for_credit` refuserait.
    """
    headers = auth_headers(token)
    payload: dict[str, Any] = {} if customer_id is None else {"customer_id": customer_id}
    sale = client.post("/api/v1/sales", headers=headers, json=payload)
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])

    item = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=headers,
        json={"product_id": product_id, "qty": qty, "discount": discount},
    )
    assert item.status_code == 201, item.text

    total = client.get(f"/api/v1/sales/{sale_id}", headers=headers).json()["total"]
    confirmed = client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=headers,
        json={"paid_amount": total if paid is None else paid, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body: dict[str, Any] = confirmed.json()
    return sale_id, str(body["items"][0]["id"]), body


def _stock_of(client: TestClient, token: str, product_id: str) -> Any:
    response = client.get("/api/v1/inventory/stock?page_size=100", headers=auth_headers(token))
    assert response.status_code == 200
    return next(item for item in response.json()["items"] if item["product_id"] == product_id)


def _create_return(
    client: TestClient, token: str, sale_id: str, sale_item_id: str, qty: str, **overrides: Any
) -> Any:
    payload: dict[str, Any] = {"lines": [{"sale_item_id": sale_item_id, "qty": qty}]}
    payload.update(overrides)
    return client.post(
        f"/api/v1/sales/{sale_id}/returns", headers=write_headers(token), json=payload
    )


# ------------------------------------------------------- le scénario de recette


def test_the_acceptance_scenario_end_to_end(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Vente de 10 à 18 %, retour de 3, remboursé à 60 % puis soldé.

    Le scénario du § 5 du prompt de phase, d'un bout à l'autre : les montants, le
    stock, le CMP, les statuts, l'audit critique et l'outbox.
    """
    headers = auth_headers(alpha_token)
    product_id = _product(api_client, alpha_token)
    sale_id, item_id, sale = _confirmed_sale(api_client, alpha_token, product_id, qty="10")

    assert sale["total"] == "11800.00", "10 × 1 000 HT, 18 % de TVA"
    assert _stock_of(api_client, alpha_token, product_id)["qty_on_hand"] == "90.000"

    # --- le retour de 3 : montants aux prix et taux historiques
    created = _create_return(
        api_client, alpha_token, sale_id, item_id, "3", reason="Article défectueux"
    )
    assert created.status_code == 201, created.text
    sale_return = created.json()
    return_id = str(sale_return["id"])

    assert sale_return["return_no"].startswith("R-")
    assert sale_return["total_refund"] == "3540.00", "3 × 1 000 × 1,18"
    assert sale_return["refunded_total"] == "0.00"
    assert sale_return["refund_due"] == "3540.00"
    assert sale_return["refund_status"] == "pending"
    assert sale_return["items"][0]["tax_refund"] == "540.00"
    # La marchandise rentre au coût de sortie, pas au CMP du jour (§ 5.3).
    assert sale_return["items"][0]["unit_cost"] == "600.0000"
    assert sale_return["refunds"] == []

    stock = _stock_of(api_client, alpha_token, product_id)
    assert stock["qty_on_hand"] == "93.000", "les 3 articles sont revenus en stock"
    assert stock["avg_cost"] == "600.0000", "le CMP ne bouge pas : même coût de part et d'autre"

    # La vente, elle, n'a pas changé : « retournée » est une information dérivée.
    after_sale = api_client.get(f"/api/v1/sales/{sale_id}", headers=headers).json()
    assert after_sale["status"] == "confirmed"
    assert after_sale["total"] == "11800.00"
    assert after_sale["has_returns"] is True
    assert after_sale["returned_total"] == "3540.00"

    # --- 60 % remboursés : le retour passe `partial`
    first = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=headers,
        json={"amount": "2124.00", "method": "cash"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["refund_status"] == "partial"
    assert first.json()["refund_due"] == "1416.00"

    # --- sur-remboursement refusé, avant même d'écrire quoi que ce soit
    too_much = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=headers,
        json={"amount": "1416.01", "method": "cash"},
    )
    assert too_much.status_code == 409
    assert too_much.json()["error"]["code"] == "refund_exceeds_due"
    assert too_much.json()["error"]["details"]["refund_due"] == "1416.00"

    # --- le solde exact, lui, passe
    second = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=headers,
        json={"amount": "1416.00", "method": "mobile_money"},
    )
    assert second.status_code == 200, second.text
    settled = second.json()
    assert settled["refunded_total"] == "3540.00"
    assert settled["refund_due"] == "0.00"
    assert settled["refund_status"] == "settled"
    assert len(settled["refunds"]) == 2
    assert {payment["direction"] for payment in settled["payments"]} == {"outflow"}
    assert [payment["method"] for payment in settled["payments"]] == ["cash", "mobile_money"]

    # --- traçabilité inverse : du paiement vers le retour qu'il a soldé
    payment_id = settled["payments"][0]["id"]
    inverse = api_client.get(f"/api/v1/payments/{payment_id}/refunded-returns", headers=headers)
    assert inverse.status_code == 200, inverse.text
    assert [row["sale_return_id"] for row in inverse.json()] == [return_id]
    assert inverse.json()[0]["amount"] == "2124.00"

    # --- audit critique et outbox, dans la transaction
    events = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM business_events "
        " WHERE event_type = 'sale.returned' AND aggregate_id = :sale_id "
        "   AND published_at IS NULL",
        {"sale_id": sale_id},
    )
    refunded_events = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM business_events "
        " WHERE event_type = 'sale_return.refunded' AND aggregate_id = :return_id",
        {"return_id": return_id},
    )
    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs "
        " WHERE entity_table = 'sale_returns' AND entity_id = :return_id",
        {"return_id": return_id},
    )
    assert events == 1
    assert refunded_events == 2, "un événement par remboursement, le refus n'en écrit aucun"
    assert audited == 3, "la création, puis chacun des deux règlements"


# ------------------------------------------------------------------- compensation


def test_a_return_can_offset_the_customer_debt(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """La compensation réduit la dette **sans** faire sortir d'argent (ADR 0024).

    C'est le cas que le § 4.6 prévoit sans dire comment l'écrire : deux paiements
    en `offset`, l'un rattaché au retour, l'autre alloué à la dette. La trésorerie
    les ignore, les lettrages les gardent.
    """
    headers = auth_headers(alpha_token)
    product_id = _product(api_client, alpha_token)
    customer_id = _customer(api_client, alpha_token)
    sale_id, item_id, sale = _confirmed_sale(
        api_client, alpha_token, product_id, qty="10", paid="0", customer_id=customer_id
    )

    assert sale["debt"]["principal"] == "11800.00"
    assert sale["debt"]["balance"] == "11800.00"

    created = _create_return(api_client, alpha_token, sale_id, item_id, "3")
    assert created.status_code == 201, created.text
    return_id = str(created.json()["id"])

    compensated = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=headers,
        json={"amount": "3540.00", "method": "offset"},
    )
    assert compensated.status_code == 200, compensated.text
    body = compensated.json()

    assert body["refund_status"] == "settled"
    assert body["refunded_total"] == "3540.00"
    assert [payment["method"] for payment in body["payments"]] == ["offset"]

    # La dette a fondu d'autant, et la vente reste intacte.
    after = api_client.get(f"/api/v1/sales/{sale_id}", headers=headers).json()
    assert after["debt"]["balance"] == "8260.00"
    assert after["debt"]["amount_paid"] == "3540.00"
    assert after["debt"]["status"] == "partially_paid"
    assert after["paid_total"] == "0.00", "rien n'a été encaissé : `paid_total` ne bouge pas"

    # Aucune écriture de trésorerie : les deux paiements portent `offset`, et c'est
    # à ce seul critère que les états des phases 07 et 08 les excluront.
    cash_movements = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM payments "
        " WHERE method <> 'offset' AND (sale_id = :sale_id OR sale_return_id = :return_id)",
        {"sale_id": sale_id, "return_id": return_id},
    )
    offsets = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM payments WHERE method = 'offset' AND created_at > now() - "
        " interval '1 minute'",
        {},
    )
    assert cash_movements == 0
    assert offsets >= 2, "un outflow pour le retour, un inflow pour la dette"


def test_a_compensation_without_an_open_debt_is_refused(
    api_client: TestClient, alpha_token: str
) -> None:
    """Sans dette ouverte sur la vente, il n'y a rien à compenser."""
    product_id = _product(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="10")
    return_id = str(_create_return(api_client, alpha_token, sale_id, item_id, "3").json()["id"])

    refused = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=auth_headers(alpha_token),
        json={"amount": "3540.00", "method": "offset"},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "no_debt_to_offset"


def test_a_compensation_larger_than_the_debt_is_refused(
    api_client: TestClient, alpha_token: str
) -> None:
    """On ne compense pas au-delà de ce que le client doit encore."""
    product_id = _product(api_client, alpha_token)
    customer_id = _customer(api_client, alpha_token)
    # Payée à 90 % : il ne reste qu'une petite dette, plus petite que le retour.
    sale_id, item_id, _ = _confirmed_sale(
        api_client, alpha_token, product_id, qty="10", paid="10800.00", customer_id=customer_id
    )
    return_id = str(_create_return(api_client, alpha_token, sale_id, item_id, "3").json()["id"])

    refused = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=auth_headers(alpha_token),
        json={"amount": "3540.00", "method": "offset"},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "offset_exceeds_debt"
    assert refused.json()["error"]["details"]["balance"] == "1000.00"


# ------------------------------------------------------------------------ refus


def test_a_draft_sale_cannot_be_returned(api_client: TestClient, alpha_token: str) -> None:
    """Un brouillon n'a rien vendu : il n'y a rien à rendre."""
    headers = auth_headers(alpha_token)
    product_id = _product(api_client, alpha_token)
    sale = api_client.post("/api/v1/sales", headers=headers, json={})
    sale_id = str(sale.json()["id"])
    item = api_client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=headers,
        json={"product_id": product_id, "qty": "2"},
    )

    refused = _create_return(api_client, alpha_token, sale_id, str(item.json()["id"]), "1")

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "sale_not_confirmed"
    assert refused.json()["error"]["details"]["status"] == "draft"


def test_a_cancelled_sale_cannot_be_returned(api_client: TestClient, alpha_token: str) -> None:
    """Une vente annulée a déjà tout repris : la reprendre deux fois créerait du stock."""
    headers = auth_headers(alpha_token)
    product_id = _product(api_client, alpha_token)
    customer_id = _customer(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(
        api_client, alpha_token, product_id, qty="2", paid="0", customer_id=customer_id
    )
    cancelled = api_client.post(
        f"/api/v1/sales/{sale_id}/cancel", headers=headers, json={"reason": "Erreur de saisie"}
    )
    assert cancelled.status_code == 200, cancelled.text

    refused = _create_return(api_client, alpha_token, sale_id, item_id, "1")

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "sale_not_confirmed"
    assert refused.json()["error"]["details"]["status"] == "cancelled"


def test_returning_more_than_was_sold_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """Le cumul est borné par la base, et le service en rend un code nommé."""
    product_id = _product(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="10")

    assert _create_return(api_client, alpha_token, sale_id, item_id, "7").status_code == 201
    refused = _create_return(api_client, alpha_token, sale_id, item_id, "4")

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "return_qty_exceeds_sold"


def test_a_line_of_another_sale_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """Rendre la ligne d'une autre vente n'a pas de sens, et la base l'ignorerait."""
    product_id = _product(api_client, alpha_token)
    sale_id, _, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="2")
    _, other_item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="2")

    refused = _create_return(api_client, alpha_token, sale_id, other_item_id, "1")

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "return_line_not_in_sale"


def test_the_same_line_cannot_appear_twice_in_one_return(
    api_client: TestClient, alpha_token: str
) -> None:
    """Deux lignes pour un même article : un 422 qui nomme le doublon."""
    product_id = _product(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="10")

    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/returns",
        headers=write_headers(alpha_token),
        json={
            "lines": [
                {"sale_item_id": item_id, "qty": "1"},
                {"sale_item_id": item_id, "qty": "2"},
            ]
        },
    )

    assert refused.status_code == 422


def test_a_return_cannot_predate_the_sale(api_client: TestClient, alpha_token: str) -> None:
    """`returned_at >= sold_at` (§ 5.3 étape 1). Aucun délai **maximal** en V1."""
    product_id = _product(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="2")

    refused = _create_return(
        api_client, alpha_token, sale_id, item_id, "1", returned_at="2020-01-01T08:00:00Z"
    )

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "return_before_sale"


def test_a_return_cannot_be_dated_in_the_future(api_client: TestClient, alpha_token: str) -> None:
    """Un retour futur n'a pas eu lieu : il ne s'enregistre pas."""
    product_id = _product(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="2")

    refused = _create_return(
        api_client, alpha_token, sale_id, item_id, "1", returned_at="2099-01-01T08:00:00Z"
    )

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "return_in_future"


def test_a_refund_of_zero_or_less_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """`CHECK (amount > 0)` doublé côté schéma : un 422 qui nomme le champ."""
    product_id = _product(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="10")
    return_id = str(_create_return(api_client, alpha_token, sale_id, item_id, "3").json()["id"])

    for amount in ("0.00", "-10.00"):
        refused = api_client.post(
            f"/api/v1/sale-returns/{return_id}/refunds",
            headers=auth_headers(alpha_token),
            json={"amount": amount, "method": "cash"},
        )
        assert refused.status_code == 422, refused.text


def test_a_sale_cannot_be_returned_with_no_line(api_client: TestClient, alpha_token: str) -> None:
    """Un retour sans ligne ne rend rien : il est refusé avant d'atteindre la base."""
    product_id = _product(api_client, alpha_token)
    sale_id, _, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="2")

    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/returns", headers=write_headers(alpha_token), json={"lines": []}
    )

    assert refused.status_code == 422


# ----------------------------------------------------------------------- lecture


def test_returns_are_listed_on_their_sale(api_client: TestClient, alpha_token: str) -> None:
    """Deux retours partiels sur la même vente, du plus récent au plus ancien."""
    headers = auth_headers(alpha_token)
    product_id = _product(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="10")

    _create_return(api_client, alpha_token, sale_id, item_id, "2")
    _create_return(api_client, alpha_token, sale_id, item_id, "3")

    listed = api_client.get(f"/api/v1/sales/{sale_id}/returns", headers=headers)

    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 2
    assert {row["total_refund"] for row in body["items"]} == {"2360.00", "3540.00"}
    assert all(row["refund_status"] == "pending" for row in body["items"])


# --------------------------------------------------------------------- droits


def test_the_seller_records_a_return_but_never_refunds(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Le comptoir enregistre la marchandise revenue ; l'argent reste au gérant.

    `sale_returns:confirm` garde le règlement comme `sales:cancel` garde
    l'annulation : dès qu'une écriture touche à la trésorerie ou à une dette, elle
    quitte la caisse (ADR 0007 et 0025).
    """
    seller = _token_for_role(api_client, alpha_token, company_alpha, "vendeur")
    product_id = _product(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="10")

    created = _create_return(api_client, seller, sale_id, item_id, "3")
    assert created.status_code == 201, created.text
    return_id = str(created.json()["id"])

    refused = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=auth_headers(seller),
        json={"amount": "100.00", "method": "cash"},
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["required_permission"] == "sale_returns:confirm"


def test_the_accountant_reads_returns_but_records_none(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Le comptable lit les retours, n'en enregistre aucun et n'en rembourse aucun."""
    accountant = _token_for_role(api_client, alpha_token, company_alpha, "comptable")
    headers = auth_headers(accountant)
    product_id = _product(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="10")
    return_id = str(_create_return(api_client, alpha_token, sale_id, item_id, "3").json()["id"])

    assert api_client.get(f"/api/v1/sale-returns/{return_id}", headers=headers).status_code == 200

    refused = _create_return(api_client, accountant, sale_id, item_id, "1")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["required_permission"] == "sale_returns:create"
