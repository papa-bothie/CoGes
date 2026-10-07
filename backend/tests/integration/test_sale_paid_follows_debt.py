"""Ce qui reste dû sur une vente suit sa dette (ADR 0062, révision 0014).

Le bug B2 de la phase 15 : un règlement de dette passe par `payment_allocations` sur la
dette (`debts.sale_id`), sans `sale_id` sur le paiement. Le trigger `sale_paid_rollup`
ne voyait que les paiements directs, donc une vente à crédit restait « Reste dû »
après le règlement complet de sa dette.

L'invariant tenu ici, lu dans la base même : pour toute vente qui porte une dette,
`total − paid_total = debts.balance`. `paid_total` veut dire « réglé » : encaissé
directement, lettré sur la dette, ou compensé par un retour (ADR 0024).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant, write_headers
from tests.integration.test_payment_cancellation import (
    PAYMENTS,
    _cancel,
    _confirmed_sale,
    _customer,
    _return,
)

pytestmark = pytest.mark.integration


def _sale(client: TestClient, token: str, sale_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _settle(
    client: TestClient, token: str, allocations: list[tuple[str, str]], *, method: str = "cash"
) -> dict[str, Any]:
    """Un encaissement **sans** `sale_id`, lettré sur une ou plusieurs dettes."""
    total = sum((Decimal(amount) for _, amount in allocations), Decimal("0"))
    created = client.post(
        PAYMENTS,
        headers=write_headers(token),
        json={
            "direction": "inflow",
            "method": method,
            "amount": str(total),
            "allocations": [{"debt_id": debt, "amount": amount} for debt, amount in allocations],
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def _invariant_breaks(session_factory: sessionmaker[Any], company: DemoCompany) -> int:
    """Ventes dont le reste dû diverge du solde de leur dette, compté en SQL direct."""
    return int(
        read_scalar_in_tenant(
            session_factory,
            company.company_id,
            "SELECT count(*) FROM sales s JOIN debts d"
            "    ON d.company_id = s.company_id AND d.sale_id = s.id"
            " WHERE d.status <> 'written_off' AND s.total - s.paid_total <> d.balance",
            {},
        )
    )


def test_settling_the_debt_marks_the_sale_paid_and_cancelling_reverts_it(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Crédit total, règlement partiel, solde, puis annulation du solde."""
    customer_id = _customer(api_client, alpha_token)
    sale = _confirmed_sale(api_client, alpha_token, paid="0", customer_id=customer_id)
    debt_id = sale["debt"]["id"]
    assert (sale["paid_total"], sale["balance"]) == ("0.00", "11800.00")

    _settle(api_client, alpha_token, [(debt_id, "5000.00")])
    partial = _sale(api_client, alpha_token, sale["id"])
    assert (partial["paid_total"], partial["balance"]) == ("5000.00", "6800.00")

    rest = _settle(api_client, alpha_token, [(debt_id, "6800.00")])
    settled = _sale(api_client, alpha_token, sale["id"])
    assert (settled["paid_total"], settled["balance"]) == ("11800.00", "0.00")
    assert settled["debt"]["status"] == "paid"
    assert settled["debt_status"] == "paid"

    assert _cancel(api_client, alpha_token, rest["id"]).status_code == 201
    reverted = _sale(api_client, alpha_token, sale["id"])
    assert (reverted["paid_total"], reverted["balance"]) == ("5000.00", "6800.00")
    assert _invariant_breaks(session_factory, company_alpha) == 0


def test_a_deposit_is_never_counted_twice(api_client: TestClient, alpha_token: str) -> None:
    """Acompte de 3 000 à la vente, dette de 8 800 pour le solde, puis solde réglé."""
    customer_id = _customer(api_client, alpha_token)
    sale = _confirmed_sale(api_client, alpha_token, paid="3000.00", customer_id=customer_id)
    assert sale["debt"]["principal"] == "8800.00"
    assert (sale["paid_total"], sale["balance"]) == ("3000.00", "8800.00")

    _settle(api_client, alpha_token, [(sale["debt"]["id"], "8800.00")])
    settled = _sale(api_client, alpha_token, sale["id"])
    assert (settled["paid_total"], settled["balance"]) == ("11800.00", "0.00")


def test_one_payment_settles_two_sales_and_its_cancellation_reopens_both(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    customer_id = _customer(api_client, alpha_token)
    first = _confirmed_sale(api_client, alpha_token, paid="0", customer_id=customer_id)
    second = _confirmed_sale(api_client, alpha_token, qty="5", paid="0", customer_id=customer_id)

    payment = _settle(
        api_client,
        alpha_token,
        [(first["debt"]["id"], "11800.00"), (second["debt"]["id"], "5900.00")],
    )
    assert _sale(api_client, alpha_token, first["id"])["balance"] == "0.00"
    assert _sale(api_client, alpha_token, second["id"])["balance"] == "0.00"

    assert _cancel(api_client, alpha_token, payment["id"]).status_code == 201
    assert _sale(api_client, alpha_token, first["id"])["balance"] == "11800.00"
    assert _sale(api_client, alpha_token, second["id"])["balance"] == "5900.00"
    assert _invariant_breaks(session_factory, company_alpha) == 0


def test_a_return_offset_against_the_debt_lowers_what_remains_due(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """3 articles rendus sur 10, déduits de la dette : il reste 8 260, partout."""
    customer_id = _customer(api_client, alpha_token)
    sale = _confirmed_sale(api_client, alpha_token, paid="0", customer_id=customer_id)
    return_id = _return(api_client, alpha_token, sale, "3")

    offset = api_client.post(
        f"/api/v1/sale-returns/{return_id}/refunds",
        headers=write_headers(alpha_token),
        json={"amount": "3540.00", "method": "offset"},
    )
    assert offset.status_code == 200, offset.text

    after = _sale(api_client, alpha_token, sale["id"])
    assert after["debt"]["balance"] == "8260.00"
    assert (after["paid_total"], after["balance"]) == ("3540.00", "8260.00")
    assert _invariant_breaks(session_factory, company_alpha) == 0


def test_a_written_off_debt_says_so_on_the_sale(api_client: TestClient, alpha_token: str) -> None:
    customer_id = _customer(api_client, alpha_token)
    sale = _confirmed_sale(api_client, alpha_token, paid="0", customer_id=customer_id)

    written_off = api_client.post(
        f"/api/v1/debts/{sale['debt']['id']}/write-off",
        headers=write_headers(alpha_token),
        json={"reason": "Client parti sans laisser d'adresse"},
    )
    assert written_off.status_code == 200, written_off.text

    after = _sale(api_client, alpha_token, sale["id"])
    assert after["debt_status"] == "written_off"
    listed = api_client.get(
        "/api/v1/sales", headers=auth_headers(alpha_token), params={"customer_id": customer_id}
    ).json()["items"]
    assert [item["debt_status"] for item in listed] == ["written_off"]
