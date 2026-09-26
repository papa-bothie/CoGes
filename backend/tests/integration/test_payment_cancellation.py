"""Annuler un paiement erroné par contre-écriture (ADR 0038, révision 0012).

Ce que ces tests tiennent, sur la vraie base et en `coges_app` :

* une annulation fait revenir **exactement** en arrière ce que le paiement avait
  produit — dette, `paid_total`, `refunded_total`, trésorerie ;
* le paiement d'origine et ses lettrages ne sont **ni modifiés ni supprimés** ;
* les refus sont nommés, et la base les porte elle-même (SQL direct) ;
* une compensation `offset` s'annule par paire.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.errors import sqlstate
from app.core.tenancy import TenantContext, tenant_transaction
from app.main import app
from app.modules.finance import service as finance_service
from tests.conftest import (
    DemoCompany,
    auth_headers,
    create_user_with_role,
    read_scalar_in_tenant,
    write_headers,
)

pytestmark = pytest.mark.integration

PAYMENTS = "/api/v1/payments"
REASON = "Saisie erronée : 50 000 au lieu de 5 000"


# ----------------------------------------------------------------- utilitaires


def _customer(client: TestClient, token: str) -> str:
    created = client.post(
        "/api/v1/customers", headers=auth_headers(token), json={"name": f"Client {uuid4().hex[:8]}"}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _supplier(client: TestClient, token: str) -> str:
    created = client.post(
        "/api/v1/suppliers",
        headers=auth_headers(token),
        json={"name": f"Fournisseur {uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _debt(client: TestClient, token: str, *, principal: str, **party: str) -> str:
    created = client.post(
        "/api/v1/debts", headers=write_headers(token), json={"principal": principal, **party}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _pay(
    client: TestClient,
    token: str,
    *,
    amount: str,
    direction: str = "inflow",
    debt_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    allocations = [] if debt_id is None else [{"debt_id": debt_id, "amount": amount}]
    created = client.post(
        PAYMENTS,
        headers=write_headers(token),
        json={
            "direction": direction,
            "method": "cash",
            "amount": amount,
            "allocations": allocations,
            **extra,
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def _cancel(
    client: TestClient, token: str, payment_id: str, *, key: str | None = None, reason: str = REASON
) -> Any:
    return client.post(
        f"{PAYMENTS}/{payment_id}/cancel",
        headers=write_headers(token, key),
        json={"reason": reason},
    )


def _debt_detail(client: TestClient, token: str, debt_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/debts/{debt_id}", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _cash(session_factory: sessionmaker[Any], company: DemoCompany) -> dict[str, Any]:
    """Trésorerie du jour, par la façade que lisent l'overview et le tableau de bord.

    Lue directement plutôt que par l'overview, qui est éventuellement cohérent
    (ADR 0034) : ce test porte sur la règle de trésorerie, pas sur le cache.
    """
    ctx = TenantContext(user_id=company.manager_id, company_id=company.company_id)
    now = datetime.now(UTC)
    start, end = now - timedelta(days=1), now + timedelta(minutes=5)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        totals = finance_service.cash_summary(session, ctx, period_from=start, period_to=end)
        daily = finance_service.daily_cash(
            session, ctx, period_from=start, period_to=end, timezone="Africa/Dakar"
        )
    return {"totals": totals, "daily": sorted(daily)}


def _rows(
    session_factory: sessionmaker[Any], company: DemoCompany, sql: str, params: dict[str, Any]
) -> list[Any]:
    ctx = TenantContext.bootstrap(company.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        return list(session.execute(text(sql), params).all())


def _snapshot(
    session_factory: sessionmaker[Any], company: DemoCompany, payment_ids: list[str]
) -> dict[str, list[Any]]:
    """Toutes les colonnes des paiements d'origine et de leurs lettrages."""
    ids = [UUID(value) for value in payment_ids]
    return {
        table: _rows(
            session_factory,
            company,
            f"SELECT to_jsonb(t) FROM {table} t WHERE {column} = ANY(:ids) ORDER BY id",
            {"ids": ids},
        )
        for table, column in (
            ("payments", "id"),
            ("payment_allocations", "payment_id"),
            ("sale_return_refunds", "payment_id"),
        )
    }


def _product(client: TestClient, token: str) -> str:
    """Un produit à 1 000 HT, taxé à 18 %, garni de 100 unités au coût de 600."""
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={
            "sku": f"SKU-{marker}",
            "name": f"Article {marker}",
            "unit_price": "1000.00",
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


def _confirmed_sale(
    client: TestClient,
    token: str,
    *,
    qty: str = "10",
    paid: str | None = None,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """Vente confirmée d'une ligne. `paid = None` : payée intégralement."""
    headers = auth_headers(token)
    product_id = _product(client, token)
    payload: dict[str, Any] = {} if customer_id is None else {"customer_id": customer_id}
    sale = client.post("/api/v1/sales", headers=headers, json=payload)
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])
    item = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=headers,
        json={"product_id": product_id, "qty": qty},
    )
    assert item.status_code == 201, item.text
    total = client.get(f"/api/v1/sales/{sale_id}", headers=headers).json()["total"]
    confirmed = client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(token),
        json={"paid_amount": total if paid is None else paid, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body: dict[str, Any] = confirmed.json()
    return body


def _return(client: TestClient, token: str, sale: dict[str, Any], qty: str) -> str:
    created = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=auth_headers(token),
        json={"lines": [{"sale_item_id": sale["items"][0]["id"], "qty": qty}]},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _sale_return(client: TestClient, token: str, return_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/sale-returns/{return_id}", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --------------------------------------------------------------- les effets


def test_cancelling_an_inflow_reopens_the_debt_and_restores_the_cash(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """50 000 encaissés sur une dette de 60 000, puis annulés : tout revient."""
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="60000"
    )
    cash_before = _cash(session_factory, company_alpha)

    payment = _pay(api_client, alpha_token, amount="50000.00", debt_id=debt_id)
    assert _debt_detail(api_client, alpha_token, debt_id)["balance"] == "10000.00"
    assert _cash(session_factory, company_alpha) != cash_before, "le paiement compte d'abord"
    originals = _snapshot(session_factory, company_alpha, [payment["id"]])

    cancelled = _cancel(api_client, alpha_token, payment["id"])
    assert cancelled.status_code == 201, cancelled.text
    body = cancelled.json()
    assert body["id"] == payment["id"], "la réponse est le paiement d'origine"
    assert body["cancelled"] is True
    assert body["cancel_reason"] == REASON
    assert body["cancelled_at"] is not None
    assert body["amount"] == "50000.00", "l'origine est lisible telle quelle"

    debt = _debt_detail(api_client, alpha_token, debt_id)
    assert (debt["status"], debt["amount_paid"], debt["balance"]) == ("open", "0.00", "60000.00")
    assert debt["closed_at"] is None

    assert _cash(session_factory, company_alpha) == cash_before, "trésorerie à l'identique"
    assert _snapshot(session_factory, company_alpha, [payment["id"]]) == originals

    # La contre-écriture : sens opposé, même montant, même moyen, sans contexte.
    reversal = api_client.get(
        f"{PAYMENTS}/{body['cancellation_id']}", headers=auth_headers(alpha_token)
    ).json()
    assert reversal["reversal_of_payment_id"] == payment["id"]
    assert (reversal["direction"], reversal["amount"], reversal["method"]) == (
        "outflow",
        "50000.00",
        "cash",
    )
    assert reversal["cancelled"] is False

    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT diff FROM audit_logs WHERE entity_table = 'payments' "
        " AND entity_id = :id AND action = 'cancel'",
        {"id": UUID(payment["id"])},
    )
    assert audited["before"]["debts"][0]["amount_paid"] == "50000.00"
    assert audited["after"]["debts"][0]["amount_paid"] == "0.00"
    assert audited["after"]["reason"] == REASON

    events = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT payload FROM business_events "
        " WHERE event_type = 'payment.cancelled' AND aggregate_id = :id",
        {"id": UUID(payment["id"])},
    )
    assert events["debt_ids"] == [debt_id]
    assert events["direction"] == "inflow"


def test_cancelling_the_last_payment_of_a_settled_debt_reopens_it(
    api_client: TestClient, alpha_token: str
) -> None:
    """Dette soldée : l'annulation du dernier règlement la rend partiellement payée."""
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="1000"
    )
    _pay(api_client, alpha_token, amount="600.00", debt_id=debt_id)
    last = _pay(api_client, alpha_token, amount="400.00", debt_id=debt_id)
    settled = _debt_detail(api_client, alpha_token, debt_id)
    assert settled["status"] == "paid" and settled["closed_at"] is not None

    assert _cancel(api_client, alpha_token, last["id"]).status_code == 201

    debt = _debt_detail(api_client, alpha_token, debt_id)
    assert (debt["status"], debt["balance"]) == ("partially_paid", "400.00")
    assert debt["closed_at"] is None


def test_cancelling_a_cash_sale_payment_resets_paid_total(
    api_client: TestClient, alpha_token: str
) -> None:
    """Vente payée comptant : `paid_total` revient à 0, et la vente redevient annulable.

    Le § 5.2 refuse d'annuler une vente encaissée ; un encaissement annulé n'est plus
    un encaissement.
    """
    sale = _confirmed_sale(api_client, alpha_token)
    payment_id = sale["payments"][0]["id"]
    assert sale["paid_total"] == sale["total"]

    assert _cancel(api_client, alpha_token, payment_id).status_code == 201

    detail = api_client.get(f"/api/v1/sales/{sale['id']}", headers=auth_headers(alpha_token))
    assert detail.json()["paid_total"] == "0.00"
    assert detail.json()["payments"][0]["cancelled"] is True

    cancelled = api_client.post(
        f"/api/v1/sales/{sale['id']}/cancel",
        headers=write_headers(alpha_token),
        json={"reason": "Vente saisie par erreur"},
    )
    assert cancelled.status_code == 200, cancelled.text


def test_cancelling_a_refund_reverts_the_return(api_client: TestClient, alpha_token: str) -> None:
    """Remboursement annulé : `refunded_total` et `refund_status` reviennent."""
    sale = _confirmed_sale(api_client, alpha_token)
    return_id = _return(api_client, alpha_token, sale, "3")
    refunded = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=write_headers(alpha_token),
        json={"amount": "3540.00", "method": "cash"},
    )
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["refund_status"] == "settled"
    payment_id = refunded.json()["payments"][0]["id"]

    assert _cancel(api_client, alpha_token, payment_id).status_code == 201

    sale_return = _sale_return(api_client, alpha_token, return_id)
    assert (sale_return["refunded_total"], sale_return["refund_status"]) == ("0.00", "pending")
    assert sale_return["payments"][0]["cancelled"] is True


def test_an_offset_is_cancelled_as_a_pair(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Compensation annulée : les deux moitiés en une fois, dette et retour reviennent."""
    customer_id = _customer(api_client, alpha_token)
    sale = _confirmed_sale(api_client, alpha_token, paid="0", customer_id=customer_id)
    debt_id = sale["debt"]["id"]
    return_id = _return(api_client, alpha_token, sale, "3")
    cash_before = _cash(session_factory, company_alpha)

    compensated = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=write_headers(alpha_token),
        json={"amount": "3540.00", "method": "offset"},
    )
    assert compensated.status_code == 200, compensated.text
    assert _debt_detail(api_client, alpha_token, debt_id)["balance"] == "8260.00"
    outflow_id = compensated.json()["payments"][0]["id"]
    inflow_id = _debt_detail(api_client, alpha_token, debt_id)["allocations"][0]["payment_id"]

    cancelled = _cancel(api_client, alpha_token, outflow_id)
    assert cancelled.status_code == 201, cancelled.text

    debt = _debt_detail(api_client, alpha_token, debt_id)
    assert (debt["status"], debt["balance"]) == ("open", "11800.00")
    sale_return = _sale_return(api_client, alpha_token, return_id)
    assert (sale_return["refunded_total"], sale_return["refund_status"]) == ("0.00", "pending")
    assert _cash(session_factory, company_alpha) == cash_before

    partner = api_client.get(f"{PAYMENTS}/{inflow_id}", headers=auth_headers(alpha_token))
    assert partner.json()["cancelled"] is True, "l'autre moitié est annulée avec la première"
    again = _cancel(api_client, alpha_token, inflow_id)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "payment_already_cancelled"


def test_supplier_and_expense_outflows_are_cancellable(
    api_client: TestClient, alpha_token: str
) -> None:
    """Même mécanique dans l'autre sens : la dette fournisseur se rouvre."""
    supplier_id = _supplier(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="supplier", supplier_id=supplier_id, principal="5000"
    )
    paid = _pay(api_client, alpha_token, amount="5000.00", direction="outflow", debt_id=debt_id)
    assert _debt_detail(api_client, alpha_token, debt_id)["status"] == "paid"
    assert _cancel(api_client, alpha_token, paid["id"]).status_code == 201
    assert _debt_detail(api_client, alpha_token, debt_id)["status"] == "open"

    category = api_client.post(
        "/api/v1/expense-categories",
        headers=auth_headers(alpha_token),
        json={"name": f"Charge {uuid4().hex[:8]}", "kind": "fixed"},
    )
    assert category.status_code == 201, category.text
    expense = api_client.post(
        "/api/v1/expenses",
        headers=write_headers(alpha_token),
        json={
            "category_id": category.json()["id"],
            "label": "Loyer",
            "amount": "20000.00",
            "spent_at": date.today().isoformat(),
        },
    )
    assert expense.status_code == 201, expense.text
    spent = _pay(
        api_client,
        alpha_token,
        amount="20000.00",
        direction="outflow",
        expense_id=expense.json()["id"],
    )
    cancelled = _cancel(api_client, alpha_token, spent["id"])
    assert cancelled.status_code == 201, cancelled.text
    assert cancelled.json()["expense_id"] == expense.json()["id"]


# ----------------------------------------------------------------- les refus


def test_cancelling_twice_is_refused_without_effect(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="900"
    )
    payment = _pay(api_client, alpha_token, amount="300.00", debt_id=debt_id)
    first = _cancel(api_client, alpha_token, payment["id"])
    assert first.status_code == 201

    second = _cancel(api_client, alpha_token, payment["id"])
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "payment_already_cancelled"

    reversals = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM payments WHERE reversal_of_payment_id = :id",
        {"id": UUID(payment["id"])},
    )
    assert reversals == 1

    refused = _cancel(api_client, alpha_token, first.json()["cancellation_id"])
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "cannot_cancel_a_reversal"


def test_a_payment_on_a_written_off_debt_cannot_be_cancelled(
    api_client: TestClient, alpha_token: str
) -> None:
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="1000"
    )
    payment = _pay(api_client, alpha_token, amount="300.00", debt_id=debt_id)
    written_off = api_client.post(
        f"/api/v1/debts/{debt_id}/write-off",
        headers=write_headers(alpha_token),
        json={"reason": "Client parti sans laisser d'adresse"},
    )
    assert written_off.status_code == 200, written_off.text

    refused = _cancel(api_client, alpha_token, payment["id"])
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "payment_debt_written_off"


def test_the_request_itself_is_validated(api_client: TestClient, alpha_token: str) -> None:
    """Motif trop court, clé absente, paiement inconnu."""
    payment = _pay(api_client, alpha_token, amount="100.00")

    too_short = _cancel(api_client, alpha_token, payment["id"], reason="erreur")
    assert too_short.status_code == 422

    # Client brut : `api_client` poserait une clé de lui-même.
    with TestClient(app) as raw_client:
        no_key = raw_client.post(
            f"{PAYMENTS}/{payment['id']}/cancel",
            headers=auth_headers(alpha_token),
            json={"reason": REASON},
        )
    assert no_key.status_code == 422, no_key.text
    assert no_key.json()["error"]["code"] == "idempotency_key_required"

    unknown = _cancel(api_client, alpha_token, str(uuid4()))
    assert unknown.status_code == 404


def test_a_replayed_key_cancels_once_and_answers_the_same(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    payment = _pay(api_client, alpha_token, amount="700.00")
    key = uuid4().hex

    first = _cancel(api_client, alpha_token, payment["id"], key=key)
    replay = _cancel(api_client, alpha_token, payment["id"], key=key)
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert (
        read_scalar_in_tenant(
            session_factory,
            company_alpha.company_id,
            "SELECT count(*) FROM payments WHERE reversal_of_payment_id = :id",
            {"id": UUID(payment["id"])},
        )
        == 1
    )

    # La même clé pour annuler un **autre** paiement n'est pas un rejeu.
    other = _pay(api_client, alpha_token, amount="800.00")
    reused = _cancel(api_client, alpha_token, other["id"], key=key)
    assert reused.status_code == 422
    assert reused.json()["error"]["code"] == "idempotency_key_reused"


def test_manager_and_accountant_may_cancel_the_salesperson_may_not(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    marker = uuid4().hex[:8]
    seller = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="vendeur",
        email=f"vendeur-{marker}@{company_alpha.slug}.example.com",
    )
    accountant = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="comptable",
        email=f"comptable-{marker}@{company_alpha.slug}.example.com",
    )
    payment = _pay(api_client, alpha_token, amount="250.00")

    assert _cancel(api_client, seller, payment["id"]).status_code == 403
    assert _cancel(api_client, accountant, payment["id"]).status_code == 201


# ------------------------------------------------------ la base, en direct


def test_the_database_rewrites_an_inconsistent_reversal(
    session_factory: sessionmaker[Any],
    company_alpha: DemoCompany,
    api_client: TestClient,
    alpha_token: str,
) -> None:
    """Montant et sens trafiqués : `payment_reversal_check` les réécrit depuis l'origine."""
    payment = _pay(api_client, alpha_token, amount="1234.00")
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        written = session.execute(
            text(
                "INSERT INTO payments (company_id, direction, method, amount, created_by, "
                " reversal_of_payment_id, cancel_reason) "
                "VALUES (:co, 'inflow', 'card', 1.00, :user, :origin, 'Essai direct') "
                "RETURNING direction, method, amount"
            ),
            {
                "co": company_alpha.company_id,
                "user": company_alpha.manager_id,
                "origin": UUID(payment["id"]),
            },
        ).one()
    assert tuple(written) == ("outflow", "cash", Decimal("1234.00"))


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        pytest.param(
            "INSERT INTO payments (company_id, direction, method, amount, created_by, "
            " reversal_of_payment_id, cancel_reason) "
            "VALUES (:co, 'inflow', 'cash', 1, :user, :reversal, 'Annuler une annulation')",
            "CG051",
            id="annulation-d-une-annulation",
        ),
        pytest.param(
            "INSERT INTO payment_allocations (company_id, payment_id, debt_id, amount) "
            "VALUES (:co, :origin, :debt, 1)",
            "CG052",
            id="imputer-un-paiement-annule",
        ),
        pytest.param(
            "INSERT INTO payments (company_id, direction, method, amount, created_by, "
            " reversal_of_payment_id, cancel_reason) "
            "VALUES (:co, 'inflow', 'cash', 1, :user, :origin, 'Seconde annulation')",
            "23505",
            id="seconde-annulation",
        ),
        pytest.param(
            "INSERT INTO payments (company_id, direction, method, amount, created_by, "
            " reversal_of_payment_id, cancel_reason, sale_id) "
            "VALUES (:co, 'inflow', 'cash', 1, :user, :fresh, 'Avec contexte', :sale)",
            "23514",
            id="annulation-avec-contexte",
        ),
    ],
)
def test_the_database_refuses_by_itself(
    statement: str,
    expected: str,
    session_factory: sessionmaker[Any],
    company_alpha: DemoCompany,
    api_client: TestClient,
    alpha_token: str,
) -> None:
    """Les refus tiennent sans l'API : SQL direct, en `coges_app`."""
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="500"
    )
    # Sans imputation : un paiement déjà épuisé lèverait `CG045` avant `CG052`.
    origin = _pay(api_client, alpha_token, amount="100.00")
    reversal_id = _cancel(api_client, alpha_token, origin["id"]).json()["cancellation_id"]
    fresh = _pay(api_client, alpha_token, amount="50.00")
    sale = _confirmed_sale(api_client, alpha_token, qty="1")

    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)
    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(statement),
            {
                "co": company_alpha.company_id,
                "user": company_alpha.manager_id,
                "origin": UUID(origin["id"]),
                "reversal": UUID(reversal_id),
                "fresh": UUID(fresh["id"]),
                "debt": UUID(debt_id),
                "sale": UUID(sale["id"]),
            },
        )
    assert sqlstate(excinfo.value) == expected, str(excinfo.value)
