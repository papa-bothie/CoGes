"""Ventes d'une année en PDF : le temps du worker pour environ 10 000 ventes (ADR 0114).

Une année de la démo (`make seed-demo` sur 366 jours, volume doublé), construite par les
façades de service comme en production, puis l'export « Ventes » de toute la période
produit par la tâche du worker : lecture figée (`REPEATABLE READ, READ ONLY`), mise en
page par paquets de 500 lignes, rangement du fichier. Le temps mesuré est noté dans
l'ADR 0114.

Hors de `make test` et de la CI : semer l'année coûte une vingtaine de minutes.
`make test-perf-volume` la lance, à la main.
Le budget attrape une régression d'un ordre de grandeur (un tableau redevenu unique, une
requête par vente), pas une latence de production.
"""

from __future__ import annotations

import io
import re
import time
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core import queue
from app.seed import seed
from app.workers.tasks import exports as export_tasks
from tests.conftest import TEST_PASSWORD, DemoCompany, auth_headers, login_token, write_headers

pytestmark = [pytest.mark.perf_volume, pytest.mark.integration]

#: Une année entière, la période la plus longue qu'un export accepte.
DAYS = 366
#: Volume de la démo doublé : un peu plus de 10 000 ventes confirmées sur l'année.
SCALE = 2.1
#: Budget du worker, en secondes, pour l'année.
BUDGET_S = 120.0


def test_a_year_of_about_10000_sales_in_pdf(
    api_client: TestClient,
    workers_bound_to_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = f"perf-pdf-{uuid4().hex[:8]}"
    started = time.perf_counter()
    company_id = seed(slug, password=TEST_PASSWORD, days=DAYS, scale=SCALE)
    seeded = time.perf_counter() - started
    company = DemoCompany(
        company_id=company_id, manager_id=UUID(int=0), slug=slug, email=f"gerant@{slug}.example.com"
    )
    token = login_token(api_client, company)
    today = api_client.get(
        "/api/v1/analytics/money?period=today", headers=auth_headers(token)
    ).json()["period_from"]
    first = (date.fromisoformat(today) - timedelta(days=DAYS - 1)).isoformat()

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        queue, "enqueue", lambda name, *, countdown=0, **kwargs: calls.append(kwargs) or True
    )
    requested = api_client.post(
        "/api/v1/exports/pdf",
        headers=write_headers(token),
        json={"kind": "sales", "date_from": first, "date_to": today},
    )
    assert requested.status_code == 202, requested.text
    started = time.perf_counter()
    assert export_tasks.build_sales(**calls[-1]) == "ready"
    built = time.perf_counter() - started

    content = api_client.get(
        f"/api/v1/exports/{requested.json()['id']}/file", headers=auth_headers(token)
    ).content
    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    # La ligne de total du tableau : « 10312 ventes ».
    count = max(int(found) for found in re.findall(r"(\d+) ventes", text))
    print(
        f"\n{count} ventes sur {DAYS} jours : semées en {seeded:.0f} s ; PDF du worker en "
        f"{built:.1f} s, {len(reader.pages)} pages, {len(content) / 1e6:.2f} Mo"
    )
    assert count >= 10_000, count
    assert built < BUDGET_S, built
