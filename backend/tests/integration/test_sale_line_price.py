"""Prix changé sur une ligne de vente (prompt 34, bloc P).

Le constat d'abord : `confirm_sale` relisait le prix courant de l'article et
l'écrivait sur la ligne. Un prix tapé sur le brouillon ne survivait donc pas à la
confirmation, et l'API ne savait même pas le recevoir.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant, write_headers
from tests.integration.test_dashboard import _product, _read
from tests.integration.test_sales_api import (
    _add_line,
    _draft,
    _make_customer,
    _make_product,
    _token_for_role,
)

pytestmark = pytest.mark.integration


def _confirm(client: TestClient, token: str, sale_id: str, paid: str) -> Any:
    return client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=auth_headers(token),
        json={"paid_amount": paid, "method": "cash"},
    )


def test_a_price_written_on_the_draft_line_survives_confirmation(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Le constat : le prix posé sur la ligne du brouillon est écrasé à la confirmation."""
    product_id = _make_product(api_client, alpha_token)  # fiche : 1 500
    customer_id = _make_customer(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token, customer_id=customer_id)
    item_id = _add_line(api_client, alpha_token, sale_id, product_id, qty="2").json()["id"]

    ctx = TenantContext.bootstrap(company_alpha.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        session.execute(
            text("UPDATE sale_items SET unit_price = 1200 WHERE id = :id"), {"id": item_id}
        )

    # À crédit : le total ne dépend pas de ce qui est encaissé.
    confirmed = _confirm(api_client, alpha_token, sale_id, "0")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["items"][0]["unit_price"] == "1200.00"
    assert confirmed.json()["total"] == "2400.00"


def test_a_typed_price_survives_confirmation(api_client: TestClient, alpha_token: str) -> None:
    """Le prix tapé à la caisse est celui que la vente garde."""
    product_id = _make_product(api_client, alpha_token)  # fiche : 1 500
    sale_id = _draft(api_client, alpha_token)
    item_id = _add_line(api_client, alpha_token, sale_id, product_id, qty="2").json()["id"]

    changed = api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{item_id}",
        headers=auth_headers(alpha_token),
        json={"unit_price": "1200.00"},
    )
    assert changed.status_code == 200, changed.text

    confirmed = _confirm(api_client, alpha_token, sale_id, "2400.00")
    assert confirmed.status_code == 200, confirmed.text
    line = confirmed.json()["items"][0]
    assert line["unit_price"] == "1200.00"
    assert line["net_amount"] == "2400.00"


# ------------------------------------------------------------ prix tapé à la caisse


def _line_with_price(
    client: TestClient, token: str, price: str, **body: Any
) -> tuple[str, str, str]:
    """Produit à 1 500 (coût 1 000), brouillon à crédit, 2 unités, prix changé."""
    product_id = _make_product(client, token)
    customer_id = _make_customer(client, token)
    sale_id = _draft(client, token, customer_id=customer_id)
    item_id = _add_line(client, token, sale_id, product_id, qty="2").json()["id"]
    changed = client.patch(
        f"/api/v1/sales/{sale_id}/items/{item_id}",
        headers=auth_headers(token),
        json={"unit_price": price, **body},
    )
    assert changed.status_code == 200, changed.text
    return product_id, sale_id, item_id


@pytest.mark.parametrize(
    ("price", "total"), [("1200.00", "2400.00"), ("2000.00", "4000.00"), ("0", "0.00")]
)
def test_a_price_can_go_lower_higher_or_to_zero(
    api_client: TestClient, alpha_token: str, price: str, total: str
) -> None:
    """Plus bas, plus haut ou cadeau : aucune limite, la fiche reste à 1 500."""
    product_id, sale_id, _ = _line_with_price(api_client, alpha_token, price)

    draft = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token)).json()
    line = draft["items"][0]
    assert (line["list_price"], line["price_changed"]) == ("1500.00", True)

    confirmed = _confirm(api_client, alpha_token, sale_id, "0")
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["total"] == total
    assert body["items"][0]["list_price"] == "1500.00"
    assert body["items"][0]["price_changed"] is True
    if total == "0.00":
        assert body["debt"] is None, "un cadeau ne laisse aucune dette"

    product = api_client.get(f"/api/v1/products/{product_id}", headers=auth_headers(alpha_token))
    assert product.json()["unit_price"] == "1500.00", "le prix de la fiche ne change pas"


def test_a_negative_price_is_refused(api_client: TestClient, alpha_token: str) -> None:
    product_id = _make_product(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token)
    item_id = _add_line(api_client, alpha_token, sale_id, product_id).json()["id"]
    refused = api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{item_id}",
        headers=auth_headers(alpha_token),
        json={"unit_price": "-1"},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["details"]["fields"][0]["field"] == "unit_price"


def test_back_to_the_usual_price_clears_the_change(
    api_client: TestClient, alpha_token: str
) -> None:
    """« Revenir au prix habituel » : le prix de la fiche, motif effacé, aucun audit."""
    _, sale_id, item_id = _line_with_price(
        api_client, alpha_token, "1200.00", price_reason="Client fidèle"
    )
    reverted = api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{item_id}",
        headers=auth_headers(alpha_token),
        json={"unit_price": "1500.00"},
    )
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["price_changed"] is False
    assert reverted.json()["price_reason"] is None

    confirmed = _confirm(api_client, alpha_token, sale_id, "0").json()
    assert confirmed["items"][0]["unit_price"] == "1500.00"
    assert confirmed["items"][0]["price_changed"] is False


def test_an_unchanged_line_follows_the_card_a_typed_one_does_not(
    api_client: TestClient, alpha_token: str
) -> None:
    """La fiche passe à 1 800 avant la confirmation : la ligne non touchée suit, l'autre non."""
    product_id = _make_product(api_client, alpha_token)
    customer_id = _make_customer(api_client, alpha_token)
    sale_id = _draft(api_client, alpha_token, customer_id=customer_id)
    untouched = _add_line(api_client, alpha_token, sale_id, product_id, qty="1").json()["id"]
    typed = _add_line(api_client, alpha_token, sale_id, product_id, qty="1").json()["id"]
    api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{typed}",
        headers=auth_headers(alpha_token),
        json={"unit_price": "1000.00"},
    )
    repriced = api_client.post(
        f"/api/v1/products/{product_id}/prices",
        headers=auth_headers(alpha_token),
        json={"unit_price": "1800.00"},
    )
    assert repriced.status_code == 201, repriced.text

    confirmed = _confirm(api_client, alpha_token, sale_id, "0").json()
    lines = {line["id"]: line for line in confirmed["items"]}
    assert (lines[untouched]["unit_price"], lines[untouched]["list_price"]) == (
        "1800.00",
        "1800.00",
    )
    assert (lines[typed]["unit_price"], lines[typed]["list_price"]) == ("1000.00", "1800.00")


def test_a_changed_price_is_audited_and_told_in_the_history(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Audit critique à la confirmation, et la phrase « Prix changé » dans l'historique."""
    _, sale_id, item_id = _line_with_price(
        api_client, alpha_token, "1200.00", price_reason="  Client fidèle  "
    )
    draft_audits = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs WHERE entity_table = 'sale_items' AND entity_id = :id",
        {"id": item_id},
    )
    assert draft_audits == 0, "un brouillon n'écrit rien dans le journal"

    confirmed = _confirm(api_client, alpha_token, sale_id, "0").json()
    assert confirmed["items"][0]["price_reason"] == "Client fidèle"
    diff = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT diff FROM audit_logs WHERE entity_table = 'sale_items' AND entity_id = :id",
        {"id": item_id},
    )
    assert diff["before"]["unit_price"] == "1500.00"
    assert diff["after"]["unit_price"] == "1200.00"
    assert diff["after"]["list_price"] == "1500.00"

    history = api_client.get("/api/v1/analytics/history", headers=auth_headers(alpha_token))
    sentences = [
        line["sentence"].replace(" ", " ").replace("\xa0", " ") for line in history.json()["items"]
    ]
    number = confirmed["sale_no"].split("-")[-1].lstrip("0")
    name = confirmed["items"][0]["product_name"]
    assert any(
        sentence.startswith("Gérante a changé le prix d")
        and name in sentence
        and f"sur la vente n° {number} : 1 500 FCFA → 1 200 FCFA (client fidèle)" in sentence
        for sentence in sentences
    ), sentences


def test_margin_revenue_and_returns_use_the_applied_price(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """2 × 1 200 au lieu de 1 000 (coût 600) : CA +2 400, marge +1 200 ; un retour rend 1 200."""
    before = _read(api_client, alpha_token, company_alpha)
    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    sale_id = _draft(api_client, alpha_token)
    item_id = _add_line(api_client, alpha_token, sale_id, product_id, qty="2").json()["id"]
    api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{item_id}",
        headers=auth_headers(alpha_token),
        json={"unit_price": "1200.00"},
    )
    assert _confirm(api_client, alpha_token, sale_id, "2400.00").status_code == 200
    after = _read(api_client, alpha_token, company_alpha)

    assert Decimal(after["revenue_today"]) - Decimal(before["revenue_today"]) == Decimal("2400")
    assert Decimal(after["estimated_margin_month"]) - Decimal(
        before["estimated_margin_month"]
    ) == Decimal("1200")

    returned = api_client.post(
        f"/api/v1/sales/{sale_id}/returns",
        headers=write_headers(alpha_token),
        json={"lines": [{"sale_item_id": item_id, "qty": "1"}]},
    )
    assert returned.status_code == 201, returned.text
    assert returned.json()["total_refund"] == "1200.00", "ce qui a été payé, pas la fiche"


def test_the_seller_changes_a_price_the_accountant_cannot(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Le droit de vendre suffit ; sans lui, le changement de prix est refusé."""
    product_id = _make_product(api_client, alpha_token)
    seller = _token_for_role(api_client, alpha_token, company_alpha, "vendeur")
    sale_id = _draft(api_client, seller)
    item_id = _add_line(api_client, seller, sale_id, product_id).json()["id"]
    by_seller = api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{item_id}",
        headers=auth_headers(seller),
        json={"unit_price": "900.00"},
    )
    assert by_seller.status_code == 200, by_seller.text

    accountant = _token_for_role(api_client, alpha_token, company_alpha, "comptable")
    refused = api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{item_id}",
        headers=auth_headers(accountant),
        json={"unit_price": "900.00"},
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["required_permission"] == "sales:update"
