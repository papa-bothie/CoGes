"""Le cycle de vente vu par l'API : brouillon, confirmation, annulation, reçu.

Ces tests-ci passent **volontairement** par l'API : ils ne mesurent pas les
garanties structurelles — c'est le rôle de T14-T17, T23, T24 et T39, qui attaquent
la base — mais le contrat rendu au client, les codes d'erreur métier et les effets
de bord attendus de chaque appel.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests.conftest import TEST_PASSWORD, DemoCompany, auth_headers, read_scalar_in_tenant

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


def _make_product(
    client: TestClient, token: str, *, stock: str | None = "100", **overrides: Any
) -> str:
    """Un produit neuf, avec son stock initial au coût de 1 000."""
    marker = uuid4().hex[:8]
    payload: dict[str, Any] = {
        "sku": f"SKU-{marker}",
        "name": f"Article {marker}",
        "unit_price": "1500.00",
    }
    payload.update(overrides)
    created = client.post("/api/v1/products", headers=auth_headers(token), json=payload)
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])

    if stock is not None:
        stocked = client.post(
            "/api/v1/inventory/movements",
            headers=auth_headers(token),
            json={
                "product_id": product_id,
                "type": "initial",
                "qty_delta": stock,
                "unit_cost": "1000",
            },
        )
        assert stocked.status_code == 201, stocked.text
    return product_id


def _make_customer(client: TestClient, token: str, **overrides: Any) -> str:
    payload: dict[str, Any] = {"name": f"Client {uuid4().hex[:8]}"}
    payload.update(overrides)
    created = client.post("/api/v1/customers", headers=auth_headers(token), json=payload)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _draft(client: TestClient, token: str, **overrides: Any) -> str:
    created = client.post("/api/v1/sales", headers=auth_headers(token), json=dict(overrides))
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _add_line(
    client: TestClient, token: str, sale_id: str, product_id: str, **overrides: Any
) -> Any:
    payload: dict[str, Any] = {"product_id": product_id, "qty": "2"}
    payload.update(overrides)
    return client.post(f"/api/v1/sales/{sale_id}/items", headers=auth_headers(token), json=payload)


def _stock_of(client: TestClient, token: str, product_id: str) -> Decimal:
    response = client.get(
        "/api/v1/inventory/stock", params={"product_id": product_id}, headers=auth_headers(token)
    )
    assert response.status_code == 200
    row = next(item for item in response.json()["items"] if item["product_id"] == product_id)
    return Decimal(row["qty_on_hand"])


# -------------------------------------------------------------------- brouillon


def test_a_draft_has_no_side_effect(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Le brouillon ne touche ni le stock, ni la finance, ni l'outbox, ni l'audit."""
    product_id = _make_product(api_client, alpha_token)
    before = _stock_of(api_client, alpha_token, product_id)

    sale_id = _draft(api_client, alpha_token)
    assert _add_line(api_client, alpha_token, sale_id, product_id, qty="3").status_code == 201

    detail = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token)).json()
    assert detail["status"] == "draft"
    assert detail["subtotal"] == "4500.00", "les totaux sont recalculés par trigger"
    assert detail["total"] == "4500.00"
    assert detail["balance"] == "4500.00"
    assert detail["has_returns"] is False

    assert _stock_of(api_client, alpha_token, product_id) == before, "le stock ne bouge pas"

    for table, clause in (
        ("payments", "sale_id = :sale_id"),
        ("debts", "sale_id = :sale_id"),
        ("business_events", "aggregate_id = :sale_id"),
        ("audit_logs", "entity_table = 'sales' AND entity_id = :sale_id"),
    ):
        count = read_scalar_in_tenant(
            session_factory,
            company_alpha.company_id,
            f"SELECT count(*) FROM {table} WHERE {clause}",
            {"sale_id": sale_id},
        )
        assert count == 0, f"un brouillon ne doit rien écrire dans {table}"


def test_sale_numbers_are_sequential_within_a_company(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """La numérotation est continue et **propre à chaque entreprise** (ADR 0021)."""
    first = api_client.post("/api/v1/sales", headers=auth_headers(alpha_token), json={}).json()
    second = api_client.post("/api/v1/sales", headers=auth_headers(alpha_token), json={}).json()
    other = api_client.post("/api/v1/sales", headers=auth_headers(beta_token), json={}).json()

    assert first["sale_no"].startswith("V-")
    assert int(second["sale_no"][2:]) == int(first["sale_no"][2:]) + 1
    # Beta a sa propre suite : elle ne saute pas parce qu'Alpha a vendu.
    assert int(other["sale_no"][2:]) <= int(first["sale_no"][2:])


def test_a_draft_line_can_be_corrected_then_removed(
    api_client: TestClient, alpha_token: str
) -> None:
    """Quantité, remise, suppression : tout reste ouvert tant que c'est un brouillon."""
    product_id = _make_product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)
    item_id = _add_line(api_client, alpha_token, sale_id, product_id, qty="2").json()["id"]

    corrected = api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{item_id}",
        headers=auth_headers(alpha_token),
        json={"qty": "5", "discount": "500.00"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["net_amount"] == "7000.00", "5 × 1500 − 500"

    removed = api_client.delete(
        f"/api/v1/sales/{sale_id}/items/{item_id}", headers=auth_headers(alpha_token)
    )
    assert removed.status_code == 204

    detail = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token)).json()
    assert detail["items"] == []
    assert detail["total"] == "0.00", "les totaux suivent la suppression"


def test_a_discount_larger_than_the_line_is_refused(
    api_client: TestClient, alpha_token: str
) -> None:
    """La remise est bornée par la base ; le service en fait une erreur nommée."""
    product_id = _make_product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)

    refused = _add_line(api_client, alpha_token, sale_id, product_id, qty="1", discount="9999.00")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "discount_exceeds_line"


def test_an_unknown_or_unsellable_product_is_refused(
    api_client: TestClient, alpha_token: str
) -> None:
    """Trois refus distincts, trois codes distincts."""
    sale_id = _draft(api_client, alpha_token)

    unknown = _add_line(api_client, alpha_token, sale_id, str(uuid4()))
    assert unknown.status_code == 404

    product_id = _make_product(api_client, alpha_token)
    api_client.patch(
        f"/api/v1/products/{product_id}",
        headers=auth_headers(alpha_token),
        json={"is_active": False},
    )
    inactive = _add_line(api_client, alpha_token, sale_id, product_id)
    assert inactive.status_code == 409
    assert inactive.json()["error"]["code"] == "product_inactive"


# ----------------------------------------------------------------- confirmation


def test_a_sale_paid_in_full_leaves_no_debt(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Paiement comptant : stock sorti, encaissement écrit, aucune dette."""
    product_id = _make_product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)
    _add_line(api_client, alpha_token, sale_id, product_id, qty="2")

    confirmed = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=auth_headers(alpha_token),
        json={"paid_amount": "3000.00", "method": "mobile_money"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()

    assert body["status"] == "confirmed"
    assert body["confirmed_at"] is not None
    assert body["total"] == "3000.00"
    assert body["paid_total"] == "3000.00", "maintenu par `sale_paid_rollup`"
    assert body["balance"] == "0.00"
    assert body["debt"] is None
    assert [payment["method"] for payment in body["payments"]] == ["mobile_money"]
    # Le coût figé vient du CMP, pas du prix de vente (§ 5.1 étape 5).
    assert body["items"][0]["unit_cost"] == "1000.0000"

    assert _stock_of(api_client, alpha_token, product_id) == Decimal("98.000")

    events = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM business_events "
        " WHERE event_type = 'sale.confirmed' AND aggregate_id = :sale_id "
        "   AND published_at IS NULL",
        {"sale_id": sale_id},
    )
    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs WHERE entity_table = 'sales' AND entity_id = :sale_id",
        {"sale_id": sale_id},
    )
    assert events == 1, "l'événement reste à publier : le relais est phase 08"
    assert audited == 1


def test_a_partial_payment_opens_a_debt_for_the_balance(
    api_client: TestClient, alpha_token: str
) -> None:
    """Paiement partiel : la dette vaut exactement ce qui reste dû."""
    product_id = _make_product(api_client, alpha_token)
    customer_id = _make_customer(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token, customer_id=customer_id)
    _add_line(api_client, alpha_token, sale_id, product_id, qty="4")

    confirmed = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=auth_headers(alpha_token),
        json={"paid_amount": "2000.00", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()

    assert body["total"] == "6000.00"
    assert body["paid_total"] == "2000.00"
    assert body["balance"] == "4000.00"
    assert body["debt"]["principal"] == "4000.00"
    assert body["debt"]["balance"] == "4000.00"
    assert body["debt"]["status"] == "open"
    assert body["debt"]["customer_id"] == customer_id


def test_a_credit_sale_requires_an_identified_customer(
    api_client: TestClient, alpha_token: str
) -> None:
    """Sans client, il n'y a personne à qui réclamer : la vente à crédit est refusée."""
    product_id = _make_product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)
    _add_line(api_client, alpha_token, sale_id, product_id)

    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm", headers=auth_headers(alpha_token), json={}
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "customer_required_for_credit"

    still_draft = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token))
    assert still_draft.json()["status"] == "draft", "le refus annule toute la confirmation"


def test_the_credit_limit_is_enforced(api_client: TestClient, alpha_token: str) -> None:
    """Plafond dépassé : refus nommé, avec l'encours et le plafond dans `details`."""
    product_id = _make_product(api_client, alpha_token)
    customer_id = _make_customer(api_client, alpha_token, credit_limit="1000.00")
    sale_id = _draft(api_client, alpha_token, customer_id=customer_id)
    _add_line(api_client, alpha_token, sale_id, product_id, qty="2")

    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm", headers=auth_headers(alpha_token), json={}
    )
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "credit_limit_exceeded"
    assert error["details"]["credit_limit"] == "1000.00"
    assert error["details"]["requested"] == "3000.00"
    assert error["details"]["outstanding"] == "0"


def test_a_payment_above_the_total_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """Le sur-paiement est refusé par défaut (Diagramme 5)."""
    product_id = _make_product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)
    _add_line(api_client, alpha_token, sale_id, product_id, qty="1")

    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=auth_headers(alpha_token),
        json={"paid_amount": "99999.00"},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "overpayment"


def test_an_empty_sale_cannot_be_confirmed(api_client: TestClient, alpha_token: str) -> None:
    """Une vente sans ligne n'est pas une vente."""
    sale_id = _draft(api_client, alpha_token)
    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm", headers=auth_headers(alpha_token), json={}
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "sale_empty"


def test_confirming_twice_is_a_conflict(api_client: TestClient, alpha_token: str) -> None:
    """La confirmation n'est pas idempotente : le second appel est un conflit (ADR 0022)."""
    product_id = _make_product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)
    _add_line(api_client, alpha_token, sale_id, product_id, qty="1")

    first = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=auth_headers(alpha_token),
        json={"paid_amount": "1500.00"},
    )
    assert first.status_code == 200, first.text

    second = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=auth_headers(alpha_token),
        json={"paid_amount": "1500.00"},
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "sale_not_draft"
    assert _stock_of(api_client, alpha_token, product_id) == Decimal("99.000"), (
        "le second appel ne doit pas ressortir la marchandise"
    )


def test_a_confirmed_sale_refuses_every_change(api_client: TestClient, alpha_token: str) -> None:
    """Lignes figées : ajout, correction et suppression sont tous refusés."""
    product_id = _make_product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)
    item_id = _add_line(api_client, alpha_token, sale_id, product_id, qty="1").json()["id"]
    api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=auth_headers(alpha_token),
        json={"paid_amount": "1500.00"},
    )

    headers = auth_headers(alpha_token)
    added = _add_line(api_client, alpha_token, sale_id, product_id)
    patched = api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{item_id}", headers=headers, json={"qty": "9"}
    )
    deleted = api_client.delete(f"/api/v1/sales/{sale_id}/items/{item_id}", headers=headers)
    renamed = api_client.patch(f"/api/v1/sales/{sale_id}", headers=headers, json={"sold_at": None})

    for response in (added, patched, deleted):
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "sale_not_draft"
    assert renamed.status_code == 409


def test_taxes_follow_the_company_setting(api_client: TestClient, alpha_token: str) -> None:
    """TVA désactivée : le taux figé vaut 0, même sur un produit taxé (ADR 0022)."""
    headers = auth_headers(alpha_token)
    product_id = _make_product(api_client, alpha_token, default_tax_rate="0.1800")

    taxed_sale = _draft(api_client, alpha_token)
    _add_line(api_client, alpha_token, taxed_sale, product_id, qty="1")
    taxed = api_client.post(
        f"/api/v1/sales/{taxed_sale}/confirm", headers=headers, json={"paid_amount": "1770.00"}
    )
    assert taxed.status_code == 200, taxed.text
    assert taxed.json()["items"][0]["tax_rate"] == "0.1800"
    assert taxed.json()["tax_total"] == "270.00"

    try:
        disabled = api_client.patch(
            "/api/v1/companies/me", headers=headers, json={"settings": {"tax_enabled": False}}
        )
        assert disabled.status_code == 200, disabled.text
        exempt_sale = _draft(api_client, alpha_token)
        _add_line(api_client, alpha_token, exempt_sale, product_id, qty="1")
        exempt = api_client.post(
            f"/api/v1/sales/{exempt_sale}/confirm", headers=headers, json={"paid_amount": "1500.00"}
        )
        assert exempt.status_code == 200, exempt.text
        assert exempt.json()["items"][0]["tax_rate"] == "0.0000"
        assert exempt.json()["tax_total"] == "0.00"

        # La vente déjà émise, elle, n'a pas bougé d'un centime.
        unchanged = api_client.get(f"/api/v1/sales/{taxed_sale}", headers=headers).json()
        assert unchanged["tax_total"] == "270.00"
    finally:
        api_client.patch("/api/v1/companies/me", headers=headers, json={"settings": {}})


# ------------------------------------------------------------------- annulation


def test_a_credit_sale_can_be_cancelled(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Annulation : stock rendu, dette abandonnée, motif conservé, événement émis."""
    headers = auth_headers(alpha_token)
    product_id = _make_product(api_client, alpha_token)
    customer_id = _make_customer(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token, customer_id=customer_id)
    _add_line(api_client, alpha_token, sale_id, product_id, qty="3")
    api_client.post(f"/api/v1/sales/{sale_id}/confirm", headers=headers, json={})

    assert _stock_of(api_client, alpha_token, product_id) == Decimal("97.000")

    cancelled = api_client.post(
        f"/api/v1/sales/{sale_id}/cancel",
        headers=headers,
        json={"reason": "Client revenu sur sa commande"},
    )
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()

    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None
    assert body["cancel_reason"] == "Client revenu sur sa commande"
    assert body["debt"]["status"] == "written_off"
    assert body["debt"]["closed_at"] is not None
    assert body["debt"]["principal"] == "4500.00", "le principal n'est jamais réécrit (§ 5.5)"

    assert _stock_of(api_client, alpha_token, product_id) == Decimal("100.000")

    events = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM business_events "
        " WHERE event_type = 'sale.cancelled' AND aggregate_id = :sale_id",
        {"sale_id": sale_id},
    )
    assert events == 1


def test_an_encashed_sale_cannot_be_cancelled(api_client: TestClient, alpha_token: str) -> None:
    """Le § 5.2 est appliqué tel quel : de l'argent encaissé se corrige par un retour."""
    headers = auth_headers(alpha_token)
    product_id = _make_product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)
    _add_line(api_client, alpha_token, sale_id, product_id, qty="2")
    api_client.post(
        f"/api/v1/sales/{sale_id}/confirm", headers=headers, json={"paid_amount": "3000.00"}
    )

    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/cancel", headers=headers, json={"reason": "Erreur de caisse"}
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "sale_has_payment"
    assert _stock_of(api_client, alpha_token, product_id) == Decimal("98.000"), (
        "le refus ne doit rien rendre au stock"
    )


def test_cancelling_twice_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """Une seconde annulation ne double pas le stock : elle est simplement refusée."""
    headers = auth_headers(alpha_token)
    product_id = _make_product(api_client, alpha_token)
    customer_id = _make_customer(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token, customer_id=customer_id)
    _add_line(api_client, alpha_token, sale_id, product_id, qty="2")
    api_client.post(f"/api/v1/sales/{sale_id}/confirm", headers=headers, json={})

    first = api_client.post(
        f"/api/v1/sales/{sale_id}/cancel", headers=headers, json={"reason": "Annulation"}
    )
    assert first.status_code == 200, first.text

    second = api_client.post(
        f"/api/v1/sales/{sale_id}/cancel", headers=headers, json={"reason": "Annulation"}
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "sale_already_cancelled"
    assert _stock_of(api_client, alpha_token, product_id) == Decimal("100.000")


def test_a_draft_cannot_be_cancelled(api_client: TestClient, alpha_token: str) -> None:
    """Un brouillon n'a rien à annuler : il n'a produit aucun effet."""
    sale_id = _draft(api_client, alpha_token)
    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/cancel",
        headers=auth_headers(alpha_token),
        json={"reason": "Abandon"},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "sale_not_confirmed"


def test_a_cancellation_without_a_reason_is_refused(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le motif est obligatoire, et le schéma le dit avant la base."""
    sale_id = _draft(api_client, alpha_token)
    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/cancel", headers=auth_headers(alpha_token), json={"reason": "  "}
    )
    assert refused.status_code == 422, refused.text


# ------------------------------------------------------------- lecture et reçu


def test_sales_can_be_filtered_and_found_by_number(
    api_client: TestClient, alpha_token: str
) -> None:
    """Statut, client et numéro exact : les trois filtres du comptoir."""
    headers = auth_headers(alpha_token)
    product_id = _make_product(api_client, alpha_token)
    customer_id = _make_customer(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token, customer_id=customer_id)
    _add_line(api_client, alpha_token, sale_id, product_id, qty="1")
    confirmed = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm", headers=headers, json={"paid_amount": "1500.00"}
    )
    sale_no = confirmed.json()["sale_no"]

    by_number = api_client.get(f"/api/v1/sales?search={sale_no}", headers=headers).json()
    assert [row["id"] for row in by_number["items"]] == [sale_id]
    assert by_number["total"] == 1

    by_customer = api_client.get(
        f"/api/v1/sales?customer_id={customer_id}&status=confirmed", headers=headers
    ).json()
    assert [row["id"] for row in by_customer["items"]] == [sale_id]

    drafts = api_client.get("/api/v1/sales?status=draft&page_size=100", headers=headers).json()
    assert sale_id not in [row["id"] for row in drafts["items"]]


def test_the_receipt_freezes_what_the_customer_paid(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le reçu est refusé sur un brouillon, et fige tout sur une vente confirmée."""
    headers = auth_headers(alpha_token)
    product_id = _make_product(api_client, alpha_token)
    customer_id = _make_customer(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token, customer_id=customer_id)
    _add_line(api_client, alpha_token, sale_id, product_id, qty="2", discount="200.00")

    too_early = api_client.get(f"/api/v1/sales/{sale_id}/receipt", headers=headers)
    assert too_early.status_code == 409
    assert too_early.json()["error"]["code"] == "sale_not_confirmed"

    api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=headers,
        json={"paid_amount": "2000.00", "method": "cash"},
    )

    receipt = api_client.get(f"/api/v1/sales/{sale_id}/receipt", headers=headers)
    assert receipt.status_code == 200, receipt.text
    body = receipt.json()

    assert body["sale_id"] == sale_id
    assert body["company"]["currency"] == "XOF"
    assert body["customer"]["id"] == customer_id
    assert body["total"] == "2800.00", "2 × 1500 − 200"
    assert body["paid_total"] == "2000.00"
    assert body["balance"] == "800.00"
    assert len(body["lines"]) == 1
    assert body["lines"][0]["discount"] == "200.00"
    assert [payment["amount"] for payment in body["payments"]] == ["2000.00"]

    # Le prix change au référentiel : le reçu, lui, ne bouge pas.
    api_client.post(
        f"/api/v1/products/{product_id}/prices", headers=headers, json={"unit_price": "9999.00"}
    )
    again = api_client.get(f"/api/v1/sales/{sale_id}/receipt", headers=headers).json()
    assert again["lines"][0]["unit_price"] == "1500.00"
    assert again["total"] == "2800.00"


# --------------------------------------------------------------------- RBAC


def test_the_seller_confirms_but_never_cancels(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Le vendeur tient la caisse ; l'annulation touche stock, finance et dette (ADR 0007)."""
    seller = _token_for_role(api_client, alpha_token, company_alpha, "vendeur")
    product_id = _make_product(api_client, alpha_token)
    customer_id = _make_customer(api_client, alpha_token)

    sale_id = _draft(api_client, seller, customer_id=customer_id)
    assert _add_line(api_client, seller, sale_id, product_id, qty="1").status_code == 201

    confirmed = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm", headers=auth_headers(seller), json={}
    )
    assert confirmed.status_code == 200, confirmed.text

    refused = api_client.post(
        f"/api/v1/sales/{sale_id}/cancel",
        headers=auth_headers(seller),
        json={"reason": "Tentative"},
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["required_permission"] == "sales:cancel"


def test_the_accountant_reads_but_never_sells(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Le comptable ne confirme aucune vente et n'en crée aucune."""
    accountant = _token_for_role(api_client, alpha_token, company_alpha, "comptable")
    headers = auth_headers(accountant)

    assert api_client.get("/api/v1/sales", headers=headers).status_code == 200

    created = api_client.post("/api/v1/sales", headers=headers, json={})
    assert created.status_code == 403
    assert created.json()["error"]["details"]["required_permission"] == "sales:create"
