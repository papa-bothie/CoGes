"""Retours après la relecture des lots 28 et 29 (prompt 32, bloc C, ADR 0103)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.sales.repository import SaleItemRepository
from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    read_scalar_in_tenant,
    write_headers,
)
from tests.integration.test_debts_api import _customer
from tests.integration.test_sales_api import _add_line, _draft, _make_product

pytestmark = pytest.mark.integration


def _fresh(client: TestClient) -> tuple[DemoCompany, str]:
    company = _create_demo_company(f"review32c-{uuid4().hex[:8]}")
    return company, login_token(client, company)


def _sale(client: TestClient, token: str, *, qty: str, paid: str) -> dict[str, Any]:
    """`qty` articles à 1 500 F, payés à hauteur de `paid`, au nom d'un client."""
    product = _make_product(client, token)
    sale = _draft(client, token, customer_id=_customer(client, token, credit_limit="1000000"))
    assert _add_line(client, token, sale, product, qty=qty).status_code == 201
    confirmed = client.post(
        f"/api/v1/sales/{sale}/confirm",
        headers=write_headers(token),
        json={"paid_amount": paid, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body: dict[str, Any] = confirmed.json()
    return body


def _return(client: TestClient, token: str, sale: dict[str, Any], qty: str) -> dict[str, Any]:
    created = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=write_headers(token),
        json={
            "lines": [{"sale_item_id": sale["items"][0]["id"], "qty": qty}],
            "offset_debt": True,
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def _refund(client: TestClient, token: str, return_id: str, amount: str, method: str) -> Any:
    return client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=write_headers(token),
        json={"amount": amount, "method": method},
    )


def _write_off(client: TestClient, token: str, debt_id: str) -> None:
    off = client.post(
        f"/api/v1/debts/{debt_id}/write-off",
        headers=auth_headers(token),
        json={"reason": "Client parti, on renonce"},
    )
    assert off.status_code == 200, off.text


# ---------------------------------------------------------------------------- C1


def test_c1_the_written_off_part_of_a_return_is_settled_without_money(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    """6 000 F, 2 000 F versés, 4 000 F abandonnés, puis tout est rendu."""
    company, boss = _fresh(api_client)
    sale = _sale(api_client, boss, qty="4", paid="2000.00")
    _write_off(api_client, boss, sale["debt"]["id"])

    created = _return(api_client, boss, sale, "4")
    assert created["total_refund"] == "6000.00"
    assert created["waived_total"] == "4000.00"
    assert created["refund_due"] == "2000.00"
    assert created["refund_status"] == "pending"

    paid_back = _refund(api_client, boss, created["id"], "2000.00", "cash")
    assert paid_back.status_code == 200, paid_back.text
    assert paid_back.json()["refund_status"] == "settled"
    assert paid_back.json()["refund_due"] == "0.00"

    lines = read_scalar_in_tenant(
        session_factory,
        company.company_id,
        "SELECT count(*) FROM audit_logs WHERE entity_table = 'sale_returns' "
        "AND entity_id = :id AND diff->'after'->>'waived_because' = 'debt_written_off' "
        "AND diff->'after'->>'waived_total' = '4000.00'",
        {"id": UUID(created["id"])},
    )
    assert lines == 1


def test_c1_nothing_was_paid_the_return_owes_nothing(api_client: TestClient) -> None:
    _, boss = _fresh(api_client)
    sale = _sale(api_client, boss, qty="2", paid="0")
    _write_off(api_client, boss, sale["debt"]["id"])
    created = _return(api_client, boss, sale, "2")
    assert created["waived_total"] == "3000.00"
    assert created["refund_due"] == "0.00"
    assert created["refund_status"] == "none_due"


def test_c1_an_open_debt_or_a_paid_sale_waives_nothing(api_client: TestClient) -> None:
    _, boss = _fresh(api_client)
    for paid in ("6000.00", "2000.00"):
        sale = _sale(api_client, boss, qty="4", paid=paid)
        created = _return(api_client, boss, sale, "4")
        assert created["waived_total"] == "0.00"


def test_c1_the_database_refuses_more_than_is_owed(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    company, boss = _fresh(api_client)
    sale = _sale(api_client, boss, qty="1", paid="1500.00")
    created = _return(api_client, boss, sale, "1")
    ctx = TenantContext(user_id=company.manager_id, company_id=company.company_id)
    with (
        pytest.raises(IntegrityError),
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text("UPDATE sale_returns SET waived_total = 1500.01 WHERE id = :id"),
            {"id": created["id"]},
        )


# ---------------------------------------------------------------------------- C2


def _sale_inflow(client: TestClient, token: str, sale_id: str) -> str:
    payments = client.get(
        "/api/v1/payments", params={"page_size": 100}, headers=auth_headers(token)
    ).json()["items"]
    return str(
        next(p["id"] for p in payments if p["direction"] == "inflow" and p["sale_id"] == sale_id)
    )


def _cancel(client: TestClient, token: str, payment_id: str) -> Any:
    return client.post(
        f"/api/v1/payments/{payment_id}/cancel",
        headers=write_headers(token),
        json={"reason": "Saisi par erreur"},
    )


def test_c2_a_payment_already_given_back_cannot_be_cancelled(api_client: TestClient) -> None:
    _, boss = _fresh(api_client)
    sale = _sale(api_client, boss, qty="2", paid="3000.00")
    created = _return(api_client, boss, sale, "2")
    refunded = _refund(api_client, boss, created["id"], "3000.00", "cash")
    assert refunded.status_code == 200, refunded.text

    refused = _cancel(api_client, boss, _sale_inflow(api_client, boss, sale["id"]))
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "refund_exceeds_paid"

    # Dans l'ordre : d'abord le remboursement, puis l'encaissement.
    refund_payment = refunded.json()["payments"][0]["id"]
    assert _cancel(api_client, boss, refund_payment).status_code == 201
    assert _cancel(api_client, boss, _sale_inflow(api_client, boss, sale["id"])).status_code == 201


def test_c2_cancelling_what_was_not_given_back_stays_allowed(api_client: TestClient) -> None:
    _, boss = _fresh(api_client)
    sale = _sale(api_client, boss, qty="2", paid="3000.00")
    created = _return(api_client, boss, sale, "1")
    assert _refund(api_client, boss, created["id"], "1500.00", "cash").status_code == 200
    # 3 000 F versés, 1 500 F rendus : l'encaissement entier ne peut plus partir…
    refused = _cancel(api_client, boss, _sale_inflow(api_client, boss, sale["id"]))
    assert refused.status_code == 409
    # …mais une vente sans retour s'annule comme avant.
    other = _sale(api_client, boss, qty="1", paid="1500.00")
    assert _cancel(api_client, boss, _sale_inflow(api_client, boss, other["id"])).status_code == 201


# ---------------------------------------------------------------------------- C3


def test_c3_returnable_reads_only_the_lines_of_the_page(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    company, boss = _fresh(api_client)
    sale = _sale(api_client, boss, qty="2", paid="3000.00")
    _return(api_client, boss, sale, "1")
    ctx = TenantContext(user_id=company.manager_id, company_id=company.company_id)
    statements: list[str] = []

    def capture(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    with tenant_transaction(ctx, session_factory=session_factory) as session:
        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            found = SaleItemRepository(session, ctx).with_returnable_qty([UUID(sale["id"])])
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    assert found == {UUID(sale["id"])}
    query = next(sql for sql in statements if "sale_return_items" in sql)
    inner = query[query.index("FROM sale_return_items") : query.index("GROUP BY")]
    # Les lignes rendues sont celles des ventes de la page, pas toute l'entreprise.
    assert "sale_id IN" in inner
