"""`GET /api/v1/dashboard` en moins de 200 ms, sur un volume réaliste.

La cible du § 1 de la phase 08. Elle n'a de sens que sur des données : mesurer une
entreprise vide prouverait seulement que FastAPI sait répondre. Le jeu est donc celui
de `make seed-demo` — une vingtaine de produits, cinquante ventes sur soixante jours,
des annulations, des retours et des charges — construit **par les façades de
service**, comme en production.

La suite est hors de `make test` : elle sème une entreprise entière, ce qui coûte
une bonne dizaine de secondes, et une boucle de développement n'a pas à le payer à
chaque exécution. `make test-perf` la lance, et la CI aussi.

Deux mesures, parce que deux choses différentes sont promises. **Cache froid** : le
tableau de bord est composé à partir d'agrégats déjà calculés, sans balayer une ligne
de vente — c'est cette promesse-là qui tient ou non sous 200 ms. **Cache chaud** :
une lecture servie depuis Redis, qui doit être franchement plus rapide, sans quoi le
cache ne gagne rien.

Ce que ce test **ne** fait **pas** : garantir une latence en production. Il mesure
une machine de développement ou un coureur de CI, à travers `TestClient`, sans réseau
ni TLS. Il attrape une régression d'un ordre de grandeur — une requête qui repart
balayer `sale_items`, un index perdu — et c'est précisément ce à quoi il sert.
"""

from __future__ import annotations

import time
from datetime import timedelta
from statistics import median
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.modules.dashboard import service as dashboard_service
from app.seed import DAYS, seed
from tests.conftest import TEST_PASSWORD, auth_headers
from tests.integration import facts_harness as facts

pytestmark = [pytest.mark.perf, pytest.mark.integration]

DASHBOARD = "/api/v1/dashboard"

#: La cible du prompt de phase, en millisecondes.
BUDGET_MS = 200.0

#: Nombre de lectures mesurées. On retient la **médiane** : une mesure unique sur une
#: machine partagée attrape le ramasse-miettes d'à côté aussi souvent qu'une vraie
#: régression.
RUNS = 9


@pytest.fixture(scope="session")
def demo_company(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> dict[str, Any]:
    """L'entreprise de `make seed-demo`, plus ses agrégats reconstruits.

    La reconstruction est ce que le worker analytique fait après COMMIT. Sans elle,
    la mesure serait celle d'un tableau de bord vide — rapide, et sans rapport avec
    ce qui est promis.
    """
    slug = f"perf-{uuid4().hex[:8]}"
    company_id = seed(slug, password=TEST_PASSWORD)

    today = facts.today_in_company(session_factory, company_id)
    facts.rebuild(
        analytics_session_factory,
        company_id,
        [today - timedelta(days=offset) for offset in range(DAYS + 1)],
    )
    return {"company_id": company_id, "slug": slug}


@pytest.fixture
def demo_token(api_client: TestClient, demo_company: dict[str, Any]) -> str:
    response = api_client.post(
        "/api/v1/auth/login",
        json={
            "company_slug": demo_company["slug"],
            "email": f"gerant@{demo_company['slug']}.example.com",
            "password": TEST_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def _timed(client: TestClient, token: str) -> tuple[float, dict[str, Any]]:
    """Une lecture chronométrée. Renvoie (millisecondes, corps)."""
    started = time.perf_counter()
    response = client.get(DASHBOARD, headers=auth_headers(token))
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return elapsed_ms, body


def test_the_dataset_is_big_enough_to_mean_something(
    api_client: TestClient, demo_token: str, demo_company: dict[str, Any]
) -> None:
    """Garde-fou : une mesure sur un jeu vide passerait toujours, et ne dirait rien.

    Il est posé en premier parce qu'une mesure de performance qui se met à mesurer
    du vide ne se signale jamais elle-même : elle devient verte, et le reste.
    """
    dashboard_service.invalidate(UUID(str(demo_company["company_id"])))
    _, body = _timed(api_client, demo_token)

    assert len(body["revenue_trend"]) == 30
    assert body["recent_sales"], "Le jeu de démonstration n'a produit aucune vente."
    assert sum(float(point["net_revenue"]) for point in body["revenue_trend"]) > 0


def test_a_cold_dashboard_answers_under_the_budget(
    api_client: TestClient, demo_token: str, demo_company: dict[str, Any]
) -> None:
    """Cache vidé avant **chaque** lecture : c'est la composition qu'on mesure."""
    company_id = UUID(str(demo_company["company_id"]))
    timings: list[float] = []
    for _ in range(RUNS):
        dashboard_service.invalidate(company_id)
        elapsed_ms, body = _timed(api_client, demo_token)
        assert body["cached"] is False
        timings.append(elapsed_ms)

    print(f"\ntableau de bord à froid : médiane {median(timings):.0f} ms sur {RUNS} lectures")
    assert median(timings) < BUDGET_MS, (
        f"Tableau de bord à froid : {median(timings):.0f} ms de médiane "
        f"(budget {BUDGET_MS:.0f} ms, mesures {[round(value) for value in timings]})"
    )


def test_a_warm_dashboard_is_faster_than_a_cold_one(
    api_client: TestClient, demo_token: str, demo_company: dict[str, Any]
) -> None:
    """Le cache doit gagner quelque chose, sinon il ne mérite pas son invalidation."""
    company_id = UUID(str(demo_company["company_id"]))
    dashboard_service.invalidate(company_id)
    cold_ms, cold = _timed(api_client, demo_token)
    assert cold["cached"] is False

    warm = [_timed(api_client, demo_token) for _ in range(RUNS)]
    assert all(body["cached"] is True for _, body in warm)
    warm_ms = median(elapsed for elapsed, _ in warm)

    print(f"\ntableau de bord à chaud : médiane {warm_ms:.0f} ms, à froid {cold_ms:.0f} ms")
    assert warm_ms < BUDGET_MS
    assert warm_ms < cold_ms, (
        f"Cache sans effet : {warm_ms:.0f} ms à chaud contre {cold_ms:.0f} ms à froid."
    )
