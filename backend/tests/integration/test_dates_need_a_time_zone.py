"""Dates saisies sans fuseau, date d'une vente confirmée un autre jour (P2.9, ADR 0088).

* `paid_at`, `returned_at`, `sold_at` sans fuseau : la comparaison avec « maintenant »
  levait `TypeError`, donc une 500. Comme pour les mouvements de stock, un 422 clair.
* Le front n'envoie jamais `sold_at` : un brouillon ouvert la veille et confirmé
  aujourd'hui gardait la date de la veille, et son chiffre d'affaires tombait sur la
  veille — ou sur un mois déjà clos. Choix du propriétaire : la confirmation recale
  `sold_at` sur son heure, sauf si une date a été saisie sur le brouillon.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from app.modules.expenses.schemas import ExpensePaymentInput
from app.modules.finance.schemas import PaymentCreate
from app.modules.sales.schemas import SaleCreate, SaleReturnCreate, SaleUpdate
from tests.conftest import DemoCompany, auth_headers, write_headers
from tests.integration.test_returns_api import _product

pytestmark = pytest.mark.integration

NAIVE = datetime(2026, 10, 1, 9, 30)  # noqa: DTZ001 - précisément ce qu'on refuse


@pytest.mark.parametrize(
    ("schema", "values"),
    [
        (
            PaymentCreate,
            {"direction": "inflow", "method": "cash", "amount": "10", "paid_at": NAIVE},
        ),
        (ExpensePaymentInput, {"method": "cash", "paid_at": NAIVE}),
        (SaleCreate, {"sold_at": NAIVE}),
        (SaleUpdate, {"sold_at": NAIVE}),
        (
            SaleReturnCreate,
            {
                "lines": [{"sale_item_id": "0" * 8 + "-0000-0000-0000-" + "0" * 12, "qty": "1"}],
                "returned_at": NAIVE,
            },
        ),
    ],
)
def test_a_date_without_time_zone_is_a_validation_error(
    schema: Any, values: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError, match="fuseau"):
        schema(**values)


def test_the_api_answers_422_not_500(api_client: TestClient, alpha_token: str) -> None:
    response = api_client.post(
        "/api/v1/payments",
        headers=write_headers(alpha_token),
        json={
            "direction": "outflow",
            "method": "cash",
            "amount": "10",
            "paid_at": NAIVE.isoformat(),
        },
    )
    assert response.status_code == 422, response.text


def _draft_with_line(client: TestClient, token: str, **sale: Any) -> str:
    created = client.post("/api/v1/sales", headers=auth_headers(token), json=sale)
    assert created.status_code == 201, created.text
    sale_id = str(created.json()["id"])
    added = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(token),
        json={"product_id": _product(client, token), "qty": "1"},
    )
    assert added.status_code == 201, added.text
    return sale_id


def _age_the_draft(owner_engine: Engine, company: DemoCompany, sale_id: str, days: int) -> None:
    """Le brouillon a été ouvert il y a `days` jours (création et date de vente)."""
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(company.company_id)}
        )
        connection.execute(
            text(
                "UPDATE sales SET created_at = created_at - make_interval(days => :d), "
                "sold_at = created_at - make_interval(days => :d) WHERE id = :id"
            ),
            {"d": days, "id": sale_id},
        )


def _confirm(client: TestClient, token: str, sale_id: str) -> dict[str, Any]:
    total = client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(token)).json()["total"]
    confirmed = client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(token),
        json={"paid_amount": total, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body: dict[str, Any] = confirmed.json()
    return body


def test_a_draft_from_yesterday_is_sold_when_it_is_confirmed(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany, owner_engine: Engine
) -> None:
    sale_id = _draft_with_line(api_client, alpha_token)
    _age_the_draft(owner_engine, company_alpha, sale_id, days=1)

    sale = _confirm(api_client, alpha_token, sale_id)

    sold_at = datetime.fromisoformat(sale["sold_at"])
    assert abs(sold_at - datetime.now(UTC)) < timedelta(minutes=5), (
        f"la vente reste datée du brouillon : {sale['sold_at']}"
    )


def test_a_date_typed_on_the_draft_is_kept(api_client: TestClient, alpha_token: str) -> None:
    typed = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0)
    sale_id = _draft_with_line(api_client, alpha_token, sold_at=typed.isoformat())

    sale = _confirm(api_client, alpha_token, sale_id)

    assert datetime.fromisoformat(sale["sold_at"]) == typed
