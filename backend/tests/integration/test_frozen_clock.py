"""Le tableau de bord suit l'heure figée (ADR 0065).

Avec `COGES_FROZEN_NOW`, « aujourd'hui » est le jour figé : une vente datée de ce jour-là
compte dans le CA du jour, et plus rien ne compte pour le vrai jour. Une entreprise neuve,
pour que les totaux se lisent sans soustraction.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.modules.dashboard import service as dashboard_service
from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    write_headers,
)
from tests.integration.test_dashboard import DASHBOARD, _product

pytestmark = pytest.mark.integration

FROZEN = (datetime.now(UTC) - timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)


@pytest.fixture(scope="module")
def shop(app_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"fige-{uuid4().hex[:8]}")


@pytest.fixture
def token(api_client: TestClient, shop: DemoCompany) -> str:
    return login_token(api_client, shop)


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("COGES_FROZEN_NOW", FROZEN.isoformat())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _today(client: TestClient, token: str, shop: DemoCompany) -> tuple[Decimal, int]:
    dashboard_service.invalidate(shop.company_id)
    body = client.get(DASHBOARD, headers=auth_headers(token)).json()
    return Decimal(body["revenue_today"]), int(body["sales_today"])


def test_a_sale_on_the_frozen_day_is_today(
    api_client: TestClient, token: str, shop: DemoCompany, frozen: None
) -> None:
    product_id = _product(api_client, token, unit_price="1000.00", unit_cost="600.00")
    sale = api_client.post(
        "/api/v1/sales",
        headers=auth_headers(token),
        json={"sold_at": (FROZEN - timedelta(hours=1)).isoformat()},
    )
    assert sale.status_code == 201, sale.text
    sale_id = sale.json()["id"]
    api_client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(token),
        json={"product_id": product_id, "qty": "2"},
    )
    confirmed = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(token),
        json={"paid_amount": "2000.00", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    assert _today(api_client, token, shop) == (Decimal("2000.00"), 1)


def test_without_frozen_time_the_real_day_is_empty(
    api_client: TestClient, token: str, shop: DemoCompany
) -> None:
    assert _today(api_client, token, shop) == (Decimal("0.00"), 0)
