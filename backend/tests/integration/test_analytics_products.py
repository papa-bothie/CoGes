"""« Quel produit ? » — et la réponse nomme toujours sa question.

Il n'existe pas de « meilleur produit ». Il existe un produit qui a généré le plus de
chiffre d'affaires, un autre qui tourne le plus vite, un troisième dont la demande
progresse — et ce ne sont pas les mêmes. La route impose donc `metric`, la renvoie
dans la réponse avec son libellé et son unité, et ne fusionne jamais deux métriques
dans un score opaque (décision 12).

La huitième métrique, le potentiel futur, vient d'un modèle de prévision qui n'existe
pas encore. Elle répond qu'elle arrive en phase 09 plutôt que d'inventer un nombre :
« données insuffisantes » est une réponse, une valeur fabriquée n'en est pas une.

**Isolement du jeu de données.** L'entreprise de test est partagée par toute la suite
et toutes les autres ventes sont datées d'aujourd'hui. Les ventes de ce module sont
donc antidatées dans une fenêtre passée qui n'appartient qu'à lui : le classement
rendu sur cette fenêtre ne contient rien d'autre.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.analytics.schemas import MAX_RANKING_LIMIT, METRIC_LABELS, ProductMetric
from tests.conftest import DemoCompany, auth_headers, create_user_with_role, write_headers
from tests.integration import facts_harness as facts

pytestmark = pytest.mark.integration

PRODUCTS = "/api/v1/analytics/products"
TIMESERIES = "/api/v1/analytics/timeseries"

#: Fenêtre d'antidatage, loin derrière les ventes du jour des autres modules. Elle
#: fait quatorze jours pour que l'évolution de la demande ait deux moitiés à comparer.
WINDOW_END_OFFSET = 40
WINDOW_DAYS = 14

_BACKDATE = text("UPDATE sales SET sold_at = :sold_at WHERE company_id = :company_id AND id = :id")


def _window(company_alpha: DemoCompany, session_factory: sessionmaker[Any]) -> tuple[date, date]:
    """Les bornes de la fenêtre réservée à ce module, dans le fuseau de l'entreprise."""
    today = facts.today_in_company(session_factory, company_alpha.company_id)
    end = today - timedelta(days=WINDOW_END_OFFSET)
    return end - timedelta(days=WINDOW_DAYS - 1), end


def _product(client: TestClient, token: str, *, unit_price: str, unit_cost: str, qty: str) -> str:
    """Un produit non taxé, garni de `qty` unités au coût demandé."""
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={
            "sku": f"RANK-{marker}",
            "name": f"Classé {marker}",
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
            "qty_delta": qty,
            "unit_cost": unit_cost,
        },
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def _sale_on(
    client: TestClient,
    token: str,
    session_factory: sessionmaker[Any],
    company_alpha: DemoCompany,
    product_id: str,
    *,
    qty: str,
    day: date,
) -> None:
    """Une vente confirmée, puis antidatée au jour voulu.

    `sales.sold_at` n'est pas borné — le mouvement de stock, lui, reste daté de la
    confirmation (ADR 0015) — ce qui permet de fabriquer un historique sans toucher
    à l'horloge ni contourner une contrainte.
    """
    sale = client.post("/api/v1/sales", headers=auth_headers(token), json={})
    assert sale.status_code == 201, sale.text
    sale_id = sale.json()["id"]

    line = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(token),
        json={"product_id": product_id, "qty": qty},
    )
    assert line.status_code == 201, line.text

    total = line.json()["line_total"]
    confirmed = client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(token),
        json={"paid_amount": total, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    ctx = TenantContext.bootstrap(company_alpha.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        session.execute(
            _BACKDATE,
            {
                "sold_at": datetime.combine(day, time(hour=12), tzinfo=UTC),
                "company_id": company_alpha.company_id,
                "id": UUID(sale_id),
            },
        )


#: Le jeu de données coûte une trentaine d'appels HTTP : il est construit une fois
#: pour le module. Une fixture de portée « module » ne convient pas — `api_client` et
#: `alpha_token` sont de portée « fonction » — d'où cette mémoïsation explicite.
_DATASET: dict[str, Any] = {}


@pytest.fixture
def _ranked(
    api_client: TestClient,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    alpha_token: str,
) -> dict[str, Any]:
    """Deux produits, vendus dans la fenêtre réservée, et les faits reconstruits.

    Le produit « fort » génère plus de chiffre d'affaires et plus de marge ; le
    produit « rapide » se vend moins cher mais en plus grand nombre, sur un stock
    plus petit — sa rotation est donc meilleure. Aucune des deux métriques ne classe
    les deux produits dans le même ordre, et c'est précisément le sujet.
    """
    if _DATASET:
        return _DATASET

    period_from, period_to = _window(company_alpha, session_factory)
    strong = _product(api_client, alpha_token, unit_price="5000.00", unit_cost="3000.00", qty="200")
    quick = _product(api_client, alpha_token, unit_price="200.00", unit_cost="100.00", qty="60")

    # Le fort : une grosse vente dans chaque moitié de la fenêtre.
    for offset in (1, WINDOW_DAYS - 2):
        _sale_on(
            api_client,
            alpha_token,
            session_factory,
            company_alpha,
            strong,
            qty="10",
            day=period_from + timedelta(days=offset),
        )
    # Le rapide : une vente par jour, en quantité croissante sur la seconde moitié.
    for offset in range(WINDOW_DAYS):
        _sale_on(
            api_client,
            alpha_token,
            session_factory,
            company_alpha,
            quick,
            qty="2" if offset < WINDOW_DAYS // 2 else "4",
            day=period_from + timedelta(days=offset),
        )

    facts.rebuild(
        analytics_session_factory,
        company_alpha.company_id,
        [period_from + timedelta(days=offset) for offset in range(WINDOW_DAYS)],
    )
    _DATASET.update({"from": period_from, "to": period_to, "strong": strong, "quick": quick})
    return _DATASET


def _ranking(client: TestClient, token: str, metric: str, ranked: dict[str, Any]) -> dict[str, Any]:
    response = client.get(
        f"{PRODUCTS}?metric={metric}&from={ranked['from']}&to={ranked['to']}&limit=50",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _value_of(body: dict[str, Any], product_id: str) -> Decimal | None:
    for row in body["items"]:
        if row["product_id"] == product_id:
            return Decimal(row["value"])
    return None


# ------------------------------------------------- la métrique est obligatoire


def test_a_ranking_without_a_metric_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """Pas de métrique par défaut : choisir à la place du gérant, c'est décider pour lui."""
    today = date.today().isoformat()
    response = api_client.get(
        f"{PRODUCTS}?from={today}&to={today}", headers=auth_headers(alpha_token)
    )

    assert response.status_code == 422


def test_an_unknown_metric_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """La liste des huit est fermée : « best » n'est pas une mesure."""
    today = date.today().isoformat()
    response = api_client.get(
        f"{PRODUCTS}?metric=best&from={today}&to={today}", headers=auth_headers(alpha_token)
    )

    assert response.status_code == 422


@pytest.mark.parametrize("metric", [metric.value for metric in ProductMetric])
def test_every_ranking_names_its_own_metric(
    api_client: TestClient, alpha_token: str, metric: str
) -> None:
    """Chaque réponse porte sa métrique, son libellé et son unité — les huit.

    L'unité compte autant que le libellé : une vélocité en unités par jour lue comme
    des francs se compare à un chiffre d'affaires, et la comparaison est absurde.
    """
    today = date.today().isoformat()
    response = api_client.get(
        f"{PRODUCTS}?metric={metric}&from={today}&to={today}", headers=auth_headers(alpha_token)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    label, unit = METRIC_LABELS[ProductMetric(metric)]
    assert body["metric"] == metric
    assert body["metric_label"] == label
    assert body["unit"] == unit


def test_the_future_potential_says_when_no_forecast_exists_yet(
    api_client: TestClient, alpha_token: str
) -> None:
    """Huitième métrique sans prévision : « données insuffisantes », pas un nombre inventé.

    Le cas où des prévisions existent est couvert par `test_intelligence_api.py`.
    """
    today = date.today().isoformat()
    response = api_client.get(
        f"{PRODUCTS}?metric=future_potential&from={today}&to={today}",
        headers=auth_headers(alpha_token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["unavailable_reason"] is not None
    assert "insuffisantes" in body["unavailable_reason"]


def test_the_ranking_length_is_bounded(api_client: TestClient, alpha_token: str) -> None:
    """Dix lignes suffisent à décider ; au-delà, c'est un export, et c'est une autre route."""
    today = date.today().isoformat()
    too_long = api_client.get(
        f"{PRODUCTS}?metric=revenue&from={today}&to={today}&limit={MAX_RANKING_LIMIT + 1}",
        headers=auth_headers(alpha_token),
    )

    assert too_long.status_code == 422


def test_an_inverted_period_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """Du 30 au 1er n'est pas une période : 422, et la borne fautive est nommée."""
    end = date.today()
    start = end - timedelta(days=5)
    response = api_client.get(
        f"{PRODUCTS}?metric=revenue&from={end.isoformat()}&to={start.isoformat()}",
        headers=auth_headers(alpha_token),
    )

    assert response.status_code == 422


# ------------------------------------------------------- les valeurs classées


def test_the_revenue_ranking_puts_the_biggest_earner_first(
    api_client: TestClient, alpha_token: str, _ranked: dict[str, Any]
) -> None:
    """2 × 10 × 5 000 = 100 000 pour le fort ; 42 × 200 = 8 400 pour le rapide."""
    body = _ranking(api_client, alpha_token, "revenue", _ranked)

    assert body["items"][0]["product_id"] == _ranked["strong"]
    assert _value_of(body, _ranked["strong"]) == Decimal("100000.00")
    assert _value_of(body, _ranked["quick"]) == Decimal("8400.00")


def test_the_margin_ranking_is_not_the_revenue_ranking(
    api_client: TestClient, alpha_token: str, _ranked: dict[str, Any]
) -> None:
    """Marge = CA net − coût net : 40 000 pour le fort, 4 200 pour le rapide."""
    body = _ranking(api_client, alpha_token, "margin", _ranked)

    assert _value_of(body, _ranked["strong"]) == Decimal("40000.00")
    assert _value_of(body, _ranked["quick"]) == Decimal("4200.00")


def test_the_quantity_ranking_reverses_the_revenue_ranking(
    api_client: TestClient, alpha_token: str, _ranked: dict[str, Any]
) -> None:
    """42 unités contre 20 : le produit le plus vendu n'est pas le plus rentable.

    C'est exactement ce que la décision 12 protège. Un classement unique ferait
    disparaître l'un des deux faits, et le gérant déciderait sur l'autre sans le savoir.
    """
    body = _ranking(api_client, alpha_token, "quantity", _ranked)

    assert body["items"][0]["product_id"] == _ranked["quick"]
    assert _value_of(body, _ranked["quick"]) == Decimal("42.000")
    assert _value_of(body, _ranked["strong"]) == Decimal("20.000")


def test_the_frequency_counts_tickets_not_units(
    api_client: TestClient, alpha_token: str, _ranked: dict[str, Any]
) -> None:
    """Quatorze ventes pour le rapide, deux pour le fort : ce sont des tickets."""
    body = _ranking(api_client, alpha_token, "frequency", _ranked)

    assert _value_of(body, _ranked["quick"]) == Decimal(WINDOW_DAYS)
    assert _value_of(body, _ranked["strong"]) == Decimal("2")


def test_the_velocity_is_a_quantity_per_day(
    api_client: TestClient, alpha_token: str, _ranked: dict[str, Any]
) -> None:
    """42 unités sur 14 jours = 3 par jour ; 20 sur 14 ≈ 1,429."""
    body = _ranking(api_client, alpha_token, "velocity", _ranked)

    assert _value_of(body, _ranked["quick"]) == Decimal("3.000")
    assert _value_of(body, _ranked["strong"]) == Decimal("1.429")


def test_the_demand_trend_compares_two_halves_of_the_period(
    api_client: TestClient, alpha_token: str, _ranked: dict[str, Any]
) -> None:
    """Le rapide passe de 2 à 4 unités par jour : +100 %.

    Le fort vend autant dans les deux moitiés, donc sa demande ne progresse pas —
    et la métrique le dit sans le classer premier pour autant.
    """
    body = _ranking(api_client, alpha_token, "demand_trend", _ranked)

    assert _value_of(body, _ranked["quick"]) == Decimal("100.00")
    assert body["items"][0]["product_id"] == _ranked["quick"]


def test_the_rotation_drops_a_product_it_cannot_measure(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> None:
    """Un stock moyen nul écarte le produit : sa rotation est indéfinie, pas faible.

    Le stock est reconstitué fin de journée par fin de journée depuis le journal
    (ADR 0033). Un produit vendu dans la fenêtre mais dont le stock n'existait pas
    encore à ces dates-là n'a pas de rotation — rendre zéro le ferait passer pour le
    pire du catalogue, ce qui est une affirmation, et elle serait fausse.
    """
    period_from, period_to = _window(company_alpha, session_factory)
    # Décalée d'une semaine : une fenêtre à soi, pour ne pas dépendre de `_ranked`.
    period_from -= timedelta(days=21)
    period_to -= timedelta(days=21)
    product_id = _product(
        api_client, alpha_token, unit_price="1000.00", unit_cost="500.00", qty="50"
    )
    _sale_on(
        api_client,
        alpha_token,
        session_factory,
        company_alpha,
        product_id,
        qty="5",
        day=period_from + timedelta(days=1),
    )
    facts.rebuild(
        analytics_session_factory,
        company_alpha.company_id,
        [period_from + timedelta(days=offset) for offset in range(WINDOW_DAYS)],
    )

    ranked = {"from": period_from, "to": period_to}
    quantity = _ranking(api_client, alpha_token, "quantity", ranked)
    rotation = _ranking(api_client, alpha_token, "rotation", ranked)

    # Il a bien vendu — la quantité le voit — mais la rotation l'écarte.
    assert _value_of(quantity, product_id) == Decimal("5.000")
    assert _value_of(rotation, product_id) is None


# ----------------------------------------------------------- séries et droits


def test_the_timeseries_leaves_no_hole(
    api_client: TestClient, alpha_token: str, _ranked: dict[str, Any]
) -> None:
    """Un jour sans vente vaut zéro et n'est jamais omis.

    Une courbe trouée se lit comme une absence de données, pas comme une caisse
    immobile : ce ne sont pas les mêmes nouvelles.
    """
    response = api_client.get(
        f"{TIMESERIES}?measure=revenue&from={_ranked['from']}&to={_ranked['to']}",
        headers=auth_headers(alpha_token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["measure"] == "revenue"
    assert body["measure_label"] == "Chiffre d'affaires net"
    assert len(body["points"]) == WINDOW_DAYS
    days = [point["day"] for point in body["points"]]
    assert days == sorted(days) and len(set(days)) == WINDOW_DAYS


def test_the_margin_series_is_below_the_revenue_series(
    api_client: TestClient, alpha_token: str, _ranked: dict[str, Any]
) -> None:
    """Deux mesures nommées, jamais fusionnées, et le coût les sépare."""
    query = f"from={_ranked['from']}&to={_ranked['to']}"
    revenue = api_client.get(
        f"{TIMESERIES}?measure=revenue&{query}", headers=auth_headers(alpha_token)
    ).json()
    margin = api_client.get(
        f"{TIMESERIES}?measure=margin&{query}", headers=auth_headers(alpha_token)
    ).json()

    assert margin["measure_label"] == "Marge brute"
    total_revenue = sum(Decimal(point["value"]) for point in revenue["points"])
    total_margin = sum(Decimal(point["value"]) for point in margin["points"])
    assert Decimal("0") < total_margin < total_revenue


def test_a_seller_cannot_read_the_product_ranking(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Une caisse encaisse ; elle n'a pas à lire la marge de l'entreprise (ADR 0007)."""
    seller_token = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="vendeur",
        email=f"vendeur-rang-{uuid4().hex[:8]}@alpha.example.com",
    )
    today = date.today().isoformat()

    response = api_client.get(
        f"{PRODUCTS}?metric=margin&from={today}&to={today}", headers=auth_headers(seller_token)
    )

    assert response.status_code == 403
