"""Le jour en cours se lit en direct (ADR 0061).

Le bug B1 de la phase 15 : sans relais d'outbox ni worker, le CA du jour ne bougeait
jamais, alors que le nombre de ventes et « Dernières ventes », lus sur `sales`,
bougeaient. Ces tests ne reconstruisent **aucun** agrégat : la suite neutralise déjà
l'enfilement des tâches (`_no_task_broker`), donc rien d'autre que l'API ne tourne.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import cache
from tests.conftest import DemoCompany, auth_headers, write_headers
from tests.integration.test_dashboard import DASHBOARD, _product, _read, _sale

pytestmark = pytest.mark.integration


def _money(body: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    return (
        Decimal(body["revenue_today"]),
        Decimal(body["revenue_month"]),
        Decimal(body["estimated_margin_month"]),
    )


def test_a_sale_moves_today_without_worker_nor_relay(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """2 unités à 1 000, coûtant 600 : +2 000 de CA du jour et du mois, +800 de marge."""
    before = _money(_read(api_client, alpha_token, company_alpha))

    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    _sale(api_client, alpha_token, product_id, qty="2", paid="2000.00")
    after = _money(_read(api_client, alpha_token, company_alpha))

    assert after[0] - before[0] == Decimal("2000.00")
    assert after[1] - before[1] == Decimal("2000.00")
    assert after[2] - before[2] == Decimal("800.00")


def test_a_cancelled_sale_leaves_today(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Paiement annulé puis vente annulée : le CA du jour revient où il était."""
    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    sale_id = _sale(api_client, alpha_token, product_id, qty="2", paid="2000.00")
    with_sale = _money(_read(api_client, alpha_token, company_alpha))

    detail = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token)).json()
    payment = api_client.post(
        f"/api/v1/payments/{detail['payments'][0]['id']}/cancel",
        headers=write_headers(alpha_token),
        json={"reason": "Saisie en double"},
    )
    assert payment.status_code == 201, payment.text
    cancelled = api_client.post(
        f"/api/v1/sales/{sale_id}/cancel",
        headers=write_headers(alpha_token),
        json={"reason": "Vente saisie par erreur"},
    )
    assert cancelled.status_code == 200, cancelled.text

    after = _money(_read(api_client, alpha_token, company_alpha))
    assert with_sale[0] - after[0] == Decimal("2000.00")
    assert with_sale[2] - after[2] == Decimal("800.00")


def test_a_return_lowers_today(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Une unité rendue sur deux : −1 000 de CA, −400 de marge, rattachés au jour de vente."""
    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    sale_id = _sale(api_client, alpha_token, product_id, qty="2", paid="2000.00")
    with_sale = _money(_read(api_client, alpha_token, company_alpha))

    detail = api_client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(alpha_token)).json()
    created = api_client.post(
        f"/api/v1/sales/{sale_id}/returns",
        headers=write_headers(alpha_token),
        json={"lines": [{"sale_item_id": detail["items"][0]["id"], "qty": "1"}]},
    )
    assert created.status_code == 201, created.text

    after = _money(_read(api_client, alpha_token, company_alpha))
    assert with_sale[0] - after[0] == Decimal("1000.00")
    assert with_sale[2] - after[2] == Decimal("400.00")


@pytest.mark.skipif(cache.get_client() is None, reason="Redis indisponible : pas de cache à tester")
def test_a_sale_flushes_the_cached_dashboard_by_itself(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Lecture mise en cache, vente, relecture : la vente se voit, sans attendre 60 s."""
    before = _read(api_client, alpha_token, company_alpha)
    assert api_client.get(DASHBOARD, headers=auth_headers(alpha_token)).json()["cached"] is True

    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    _sale(api_client, alpha_token, product_id, qty="1", paid="1000.00")

    again = api_client.get(DASHBOARD, headers=auth_headers(alpha_token)).json()
    assert again["cached"] is False
    assert Decimal(again["revenue_today"]) - Decimal(before["revenue_today"]) == Decimal("1000.00")
