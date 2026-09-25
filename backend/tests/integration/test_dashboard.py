"""L'écran d'ouverture de la journée : ce qu'il montre, et ce qu'il coûte.

Le tableau de bord ne calcule rien. Chaque chiffre vient de la façade du module qui
le possède, et le chiffre d'affaires vient d'agrégats **déjà construits** — c'est la
condition pour tenir sous 200 ms (décision 14). La mesure de latence, elle, vit dans
`tests/perf/` : elle demande un volume que la suite d'intégration n'a pas à porter.

Trois propriétés sont vérifiées ici.

**La composition est juste** : le jour, le mois, la marge estimée, les créances, les
alertes, la courbe de trente jours et les cinq dernières ventes.

**Le cache est transparent** : une réponse servie depuis Redis est identique à une
réponse recalculée, au drapeau `cached` près — sans quoi le cache ne serait pas une
optimisation mais une seconde vérité.

**Le fil d'alertes est personnel** : le tableau de bord n'affiche jamais les alertes
d'un autre, même à un gérant.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core import cache
from app.core.events.inbox import Event
from app.core.events.types import EventType
from app.modules.dashboard import service as dashboard_service
from app.modules.dashboard.schemas import ACTIVE_ALERTS, RECENT_SALES, REVENUE_TREND_DAYS
from app.modules.inventory.events import stock_updated_payload
from app.workers.tasks.notifications import on_stock_updated
from tests.conftest import DemoCompany, auth_headers, create_user_with_role, write_headers
from tests.integration import facts_harness as facts

pytestmark = pytest.mark.integration

DASHBOARD = "/api/v1/dashboard"


def _read(client: TestClient, token: str, company: DemoCompany) -> dict[str, Any]:
    """Lit le tableau de bord **sans** cache, en l'invalidant d'abord.

    Presque tous les tests de ce module modifient les données puis relisent : servir
    une réponse de moins de soixante secondes les ferait tous échouer pour la même
    raison, qui n'est pas celle qu'ils éprouvent. Le cache a son propre test.
    """
    dashboard_service.invalidate(company.company_id)
    response = client.get(DASHBOARD, headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _product(client: TestClient, token: str, *, unit_price: str, unit_cost: str) -> str:
    """Un produit non taxé, garni de 100 unités : la marge se lit sans arithmétique de TVA."""
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={
            "sku": f"DASH-{marker}",
            "name": f"Tableau {marker}",
            "unit_price": unit_price,
            "default_tax_rate": "0",
        },
    )
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])

    stocked = client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={
            "product_id": product_id,
            "type": "initial",
            "qty_delta": "100",
            "unit_cost": unit_cost,
        },
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def _sale(client: TestClient, token: str, product_id: str, *, qty: str, paid: str) -> str:
    sale = client.post("/api/v1/sales", headers=auth_headers(token), json={})
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])

    line = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(token),
        json={"product_id": product_id, "qty": qty},
    )
    assert line.status_code == 201, line.text

    confirmed = client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(token),
        json={"paid_amount": paid, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return sale_id


# ------------------------------------------------------------- la composition


def test_a_confirmed_sale_moves_the_day_the_month_and_the_margin(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> None:
    """2 unités à 1 000, coûtant 600 : +2 000 de CA, +800 de marge, +1 vente.

    La marge est dite « estimée » parce qu'elle est brute : ni amortissement, ni
    provision, ni charge d'exploitation. C'est la question du gérant, pas celle de son
    expert-comptable (décision 09) — et le nom du champ le dit.
    """
    facts.rebuild_around(analytics_session_factory, session_factory, company_alpha.company_id)
    before = _read(api_client, alpha_token, company_alpha)

    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    _sale(api_client, alpha_token, product_id, qty="2", paid="2000.00")
    facts.rebuild_around(analytics_session_factory, session_factory, company_alpha.company_id)
    after = _read(api_client, alpha_token, company_alpha)

    assert Decimal(after["revenue_today"]) - Decimal(before["revenue_today"]) == Decimal("2000.00")
    assert Decimal(after["revenue_month"]) - Decimal(before["revenue_month"]) == Decimal("2000.00")
    assert Decimal(after["estimated_margin_month"]) - Decimal(
        before["estimated_margin_month"]
    ) == Decimal("800.00")
    assert after["sales_today"] == before["sales_today"] + 1


def test_the_reference_dates_frame_the_current_month(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Le jour et le mois sont ceux du **fuseau de l'entreprise**, pas d'UTC.

    Un gérant à Dakar qui ouvre son écran à 23 h 30 doit voir sa journée, pas celle
    de Londres — la nuance est invisible à Dakar et décisive à Abidjan comme à Douala.
    """
    body = _read(api_client, alpha_token, company_alpha)

    today = facts.today_in_company(session_factory, company_alpha.company_id)
    assert date.fromisoformat(body["today"]) == today
    assert date.fromisoformat(body["month_from"]) == today.replace(day=1)
    assert date.fromisoformat(body["month_to"]) == today


def test_the_trend_covers_thirty_days_without_a_hole(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Trente points consécutifs, jours creux à zéro.

    Une courbe trouée se lit comme une absence de données, pas comme une caisse
    immobile : ce ne sont pas les mêmes nouvelles.
    """
    body = _read(api_client, alpha_token, company_alpha)

    days = [date.fromisoformat(point["day"]) for point in body["revenue_trend"]]
    assert len(days) == REVENUE_TREND_DAYS
    assert days == sorted(days)
    assert days[-1] - days[0] == timedelta(days=REVENUE_TREND_DAYS - 1)
    assert date.fromisoformat(body["today"]) == days[-1]


def test_an_unpaid_sale_shows_up_in_the_receivables(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """La créance vient de Finance, pas des faits : elle bouge sans reconstruction."""
    customer = api_client.post(
        "/api/v1/customers",
        headers=auth_headers(alpha_token),
        json={"name": f"Client {uuid4().hex[:6]}"},
    )
    assert customer.status_code == 201, customer.text
    before = _read(api_client, alpha_token, company_alpha)

    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    sale = api_client.post(
        "/api/v1/sales",
        headers=auth_headers(alpha_token),
        json={"customer_id": customer.json()["id"]},
    )
    assert sale.status_code == 201, sale.text
    sale_id = sale.json()["id"]
    line = api_client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(alpha_token),
        json={"product_id": product_id, "qty": "3"},
    )
    assert line.status_code == 201, line.text
    confirmed = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(alpha_token),
        json={"paid_amount": "0.00", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    after = _read(api_client, alpha_token, company_alpha)
    assert Decimal(after["receivables_open"]) - Decimal(before["receivables_open"]) == Decimal(
        "3000.00"
    )


def test_the_recent_sales_are_the_five_latest_confirmed_ones(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Cinq lignes au plus, les plus récentes d'abord, chacune nommée par son numéro."""
    product_id = _product(api_client, alpha_token, unit_price="500.00", unit_cost="200.00")
    for _ in range(RECENT_SALES + 1):
        _sale(api_client, alpha_token, product_id, qty="1", paid="500.00")

    body = _read(api_client, alpha_token, company_alpha)

    recent = body["recent_sales"]
    assert len(recent) == RECENT_SALES
    sold_at = [datetime.fromisoformat(sale["sold_at"]) for sale in recent]
    assert sold_at == sorted(sold_at, reverse=True)
    assert all(sale["sale_no"].startswith("V-") for sale in recent)


def test_a_product_under_its_threshold_is_counted_and_alerted(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Le compteur d'alertes vient du stock ; le fil vient des notifications.

    Deux sources, deux questions différentes : « combien d'articles sont en danger »
    n'est pas « de quoi m'a-t-on prévenu ». Un produit peut être sous son seuil sans
    que personne n'ait encore été alerté — c'est même l'état normal juste après la
    vente qui a franchi le seuil, avant que le worker ne passe.
    """
    before = _read(api_client, alpha_token, company_alpha)

    marker = uuid4().hex[:8]
    created = api_client.post(
        "/api/v1/products",
        headers=auth_headers(alpha_token),
        json={
            "sku": f"SEUIL-{marker}",
            "name": f"Sous le seuil {marker}",
            "unit_price": "1000.00",
            "default_tax_rate": "0",
            "reorder_point": "10.000",
        },
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["id"]
    stocked = api_client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(alpha_token),
        json={"product_id": product_id, "type": "initial", "qty_delta": "4", "unit_cost": "600"},
    )
    assert stocked.status_code == 201, stocked.text

    after = _read(api_client, alpha_token, company_alpha)
    assert after["stock_alert_count"] == before["stock_alert_count"] + 1


def test_the_active_alerts_are_the_readers_own_unread_ones(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Cinq alertes non lues au plus, celles de l'utilisateur du jeton et d'aucun autre."""
    seller_token = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="vendeur",
        email=f"vendeur-tdb-{uuid4().hex[:8]}@alpha.example.com",
    )
    product_id = _product(api_client, alpha_token, unit_price="1000.00", unit_cost="600.00")
    on_stock_updated(
        **Event(
            id=910_000_001,
            company_id=company_alpha.company_id,
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

    manager = _read(api_client, alpha_token, company_alpha)
    seller = _read(api_client, seller_token, company_alpha)

    assert len(manager["active_alerts"]) <= ACTIVE_ALERTS
    assert any(alert["type"] == "stock_out" for alert in manager["active_alerts"])
    # Le vendeur n'a pas `inventory:update` : l'alerte ne lui a jamais été adressée.
    assert seller["active_alerts"] == []


# ------------------------------------------------------------------- le cache


@pytest.mark.skipif(cache.get_client() is None, reason="Redis indisponible : pas de cache à tester")
def test_the_cache_serves_the_same_answer_and_says_so(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Deuxième lecture : même contenu, `cached` à vrai. Rien d'autre ne change.

    C'est la condition pour que le cache reste une optimisation. S'il pouvait rendre
    une réponse différente, il deviendrait une seconde source de vérité — et celle
    des deux qu'on croirait serait affaire de hasard.
    """
    fresh = _read(api_client, alpha_token, company_alpha)
    again = api_client.get(DASHBOARD, headers=auth_headers(alpha_token))

    assert again.status_code == 200, again.text
    cached = again.json()
    assert cached["cached"] is True
    assert fresh["cached"] is False
    assert {key: value for key, value in cached.items() if key != "cached"} == {
        key: value for key, value in fresh.items() if key != "cached"
    }


@pytest.mark.skipif(cache.get_client() is None, reason="Redis indisponible : pas de cache à tester")
def test_invalidating_the_cache_makes_the_dashboard_recompute(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """L'invalidation par événement : ce que les consommateurs appellent après COMMIT."""
    _read(api_client, alpha_token, company_alpha)
    assert api_client.get(DASHBOARD, headers=auth_headers(alpha_token)).json()["cached"] is True

    dashboard_service.invalidate(company_alpha.company_id)

    assert api_client.get(DASHBOARD, headers=auth_headers(alpha_token)).json()["cached"] is False


@pytest.mark.skipif(cache.get_client() is None, reason="Redis indisponible : pas de cache à tester")
def test_the_cache_key_never_crosses_a_tenant(
    api_client: TestClient,
    alpha_token: str,
    beta_token: str,
    company_alpha: DemoCompany,
    company_beta: DemoCompany,
) -> None:
    """Aucune RLS ne veille sur Redis : la clé porte le `company_id`, et c'est tout.

    Le test attaque la question par les deux bouts : les deux clés diffèrent, et le
    tableau de bord de beta ne raconte jamais la journée d'alpha.
    """
    alpha = _read(api_client, alpha_token, company_alpha)
    beta = _read(api_client, beta_token, company_beta)

    assert cache.key(company_alpha.company_id, dashboard_service.CACHE_KEY) != cache.key(
        company_beta.company_id, dashboard_service.CACHE_KEY
    )
    alpha_sales = {sale["id"] for sale in alpha["recent_sales"]}
    beta_sales = {sale["id"] for sale in beta["recent_sales"]}
    assert alpha_sales.isdisjoint(beta_sales)


# ------------------------------------------------------------------- le droit


def test_a_seller_may_open_the_dashboard(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """`dashboard:read` appartient aux trois rôles : c'est l'écran d'ouverture, pas un rapport."""
    seller_token = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="vendeur",
        email=f"vendeur-ouvre-{uuid4().hex[:8]}@alpha.example.com",
    )

    response = api_client.get(DASHBOARD, headers=auth_headers(seller_token))

    assert response.status_code == 200, response.text


def test_the_dashboard_is_closed_without_a_token(api_client: TestClient) -> None:
    response = api_client.get(DASHBOARD)

    assert response.status_code == 401
