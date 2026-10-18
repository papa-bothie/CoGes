"""Le tableau de bord en cache, vu par chacun (prompt 21, P1.7 ; ADR 0087).

Le cache est **par entreprise** (60 s) ; or les alertes actives sont celles **de la
personne connectée**. Mises dans le cache, celles du premier lecteur étaient servies au
suivant : le vendeur voyait les alertes du gérant, et une alerte lue restait « non
lue » une minute.

Même défaut pour ce que le vendeur ne doit pas lire : la marge (`analytics:read`,
ADR 0030), ce qui est dû (`debts:read`, ADR 0072) et la caisse (`analytics:read`, le
droit de `/analytics/cash`). Le front les masquait, le JSON les portait.

Aucune invalidation ici entre deux lectures : c'est précisément le cache qui est éprouvé.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import cache
from app.core.events.inbox import Event
from app.core.events.types import EventType
from app.modules.dashboard import service as dashboard_service
from app.modules.inventory.events import stock_updated_payload
from app.workers.tasks.notifications import on_stock_updated
from tests.conftest import DemoCompany, auth_headers, create_user_with_role
from tests.integration.test_dashboard import _product

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(cache.get_client() is None, reason="Redis indisponible : pas de cache"),
]

DASHBOARD = "/api/v1/dashboard"
#: Ce que le vendeur ne lit pas, et le droit qui l'ouvre.
RESTRICTED = {
    "estimated_margin_month": "analytics:read",
    "cash_on_hand": "analytics:read",
    "receivables_open": "debts:read",
    "receivables_customer_count": "debts:read",
    "watch_debt": "debts:read",
}


def _get(client: TestClient, token: str) -> dict[str, Any]:
    response = client.get(DASHBOARD, headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _seller(client: TestClient, token: str, company: DemoCompany) -> str:
    return create_user_with_role(
        client,
        token,
        company,
        role="vendeur",
        email=f"vendeur-cache-{uuid4().hex[:8]}@alpha.example.com",
    )


def _stock_out_alert(company: DemoCompany, product_id: str) -> None:
    """Rupture annoncée : l'alerte part vers ceux qui ont `inventory:update` (le gérant)."""
    on_stock_updated(
        **Event(
            id=920_000_000 + int(uuid4().int % 1_000_000),
            company_id=company.company_id,
            event_type=EventType.STOCK_UPDATED,
            aggregate_type="product",
            aggregate_id=UUID(product_id),
            payload=stock_updated_payload(
                product_id=UUID(product_id),
                qty_on_hand=Decimal("0.000"),
                avg_cost=Decimal("600.0000"),
                movement_id=uuid4(),
                below_reorder_point=True,
            ),
            occurred_at=datetime.now(UTC),
        ).as_message()
    )


def test_the_seller_never_gets_the_managers_alerts_from_the_cache(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    seller_token = _seller(api_client, alpha_token, company_alpha)
    _stock_out_alert(
        company_alpha, _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    )
    dashboard_service.invalidate(company_alpha.company_id)

    manager = _get(api_client, alpha_token)  # remplit le cache
    seller = _get(api_client, seller_token)

    assert any(alert["type"] == "stock_out" for alert in manager["active_alerts"])
    assert seller["cached"] is True, "le second lecteur doit bien passer par le cache"
    assert seller["active_alerts"] == [], "le vendeur reçoit les alertes du gérant"


def test_an_alert_read_disappears_at_once(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    _stock_out_alert(
        company_alpha, _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    )
    dashboard_service.invalidate(company_alpha.company_id)
    assert _get(api_client, alpha_token)["active_alerts"]  # remplit le cache

    read_all = api_client.post("/api/v1/notifications/read-all", headers=auth_headers(alpha_token))
    assert read_all.status_code == 200, read_all.text

    after = _get(api_client, alpha_token)
    assert after["cached"] is True
    assert after["active_alerts"] == [], "une alerte lue reste affichée tant que le cache vit"


@pytest.mark.parametrize("seller_first", [True, False])
def test_the_seller_never_receives_money_figures(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany, seller_first: bool
) -> None:
    """Quel que soit celui qui a rempli le cache."""
    seller_token = _seller(api_client, alpha_token, company_alpha)
    dashboard_service.invalidate(company_alpha.company_id)

    if seller_first:
        seller = _get(api_client, seller_token)
        manager = _get(api_client, alpha_token)
    else:
        manager = _get(api_client, alpha_token)
        seller = _get(api_client, seller_token)

    leaked = {field: seller[field] for field in RESTRICTED if seller.get(field) is not None}
    assert leaked == {}, f"le vendeur reçoit : {leaked}"
    for field in ("estimated_margin_month", "cash_on_hand", "receivables_open"):
        assert manager[field] is not None, f"le gérant a perdu {field}"
