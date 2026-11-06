"""Exports PDF pour le comptable (prompt 35, bloc X, ADR 0114).

Une boutique neuve, des données connues : chaque PDF est relu par pypdf, ses totaux sont
comparés à ceux de **l'écran** correspondant pour la même période (et à l'Excel des
ventes), et l'accès est vérifié (droit de lecture, droit d'export, autre entreprise).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core import queue
from app.modules.analytics.reports import aging_bucket
from app.workers.tasks import exports as export_tasks
from tests.conftest import (
    TEST_PASSWORD,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    write_headers,
)

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- aides


def _post(client: TestClient, token: str, path: str, body: Any) -> dict[str, Any]:
    response = client.post(path, headers=write_headers(token), json=body)
    assert response.status_code in (200, 201, 202), f"{path} : {response.text}"
    return dict(response.json())


def _text(content: bytes) -> str:
    assert content.startswith(b"%PDF-"), content[:80]
    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    # pypdf ouvre chaque cellule alignée à droite par une espace : « Total\n 4 500 F ».
    return re.sub(r"\n +", "\n", text)


def _f(value: str | Decimal) -> str:
    """« 4500.00 » → « 4 500 F » (le format des PDF, comme le reçu à l'écran)."""
    whole = int(Decimal(value).quantize(Decimal(1)))
    sign = "-" if whole < 0 else ""
    return f"{sign}{abs(whole):,}".replace(",", " ") + " F"


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def record(task_name: str, *, countdown: int = 0, **kwargs: Any) -> bool:
        calls.append((task_name, kwargs))
        return True

    monkeypatch.setattr(queue, "enqueue", record)
    return calls


class Shop:
    def __init__(self, company: DemoCompany, token: str, today: date) -> None:
        self.company = company
        self.token = token
        self.today = today


@pytest.fixture(scope="module")
def shop(app_bound_to_test_database: None) -> Shop:
    """Données connues, toutes datées d'aujourd'hui (heure de Dakar)."""
    from app.main import app
    from tests.conftest import TEST_BASE_URL, _IdempotentClient

    company = _create_demo_company(f"compta-{uuid4().hex[:8]}")
    with _IdempotentClient(app, base_url=TEST_BASE_URL) as client:
        token = login_token(client, company)
        client.patch(
            "/api/v1/companies/me",
            headers=auth_headers(token),
            json={"name": "Boutique Compta", "address": "Rue 10, Dakar", "ninea": "0099887"},
        )
        today = date.fromisoformat(
            client.get("/api/v1/analytics/money?period=today", headers=auth_headers(token)).json()[
                "period_from"
            ]
        )
        category = _post(client, token, "/api/v1/categories", {"name": "Épicerie"})["id"]
        product = _post(
            client,
            token,
            "/api/v1/products",
            {"name": "Riz parfumé", "unit_price": "1500", "unit": "sac", "category_id": category},
        )["id"]
        _post(
            client,
            token,
            "/api/v1/inventory/movements",
            {"product_id": product, "type": "initial", "qty_delta": "50", "unit_cost": "900"},
        )
        customer = _post(client, token, "/api/v1/customers", {"name": "Awa Ndiaye"})["id"]
        supplier = _post(client, token, "/api/v1/suppliers", {"name": "Grossiste Fall"})["id"]

        # Vente 1 : 2 sacs, 3 000 F en espèces.
        first = _post(client, token, "/api/v1/sales", {})["id"]
        _post(client, token, f"/api/v1/sales/{first}/items", {"product_id": product, "qty": "2"})
        _post(
            client,
            token,
            f"/api/v1/sales/{first}/confirm",
            {"paid_amount": "3000", "method": "cash"},
        )
        # Vente 2 : 1 sac à Awa, 1 000 F par Wave, 500 F à crédit.
        second = _post(client, token, "/api/v1/sales", {"customer_id": customer})["id"]
        _post(client, token, f"/api/v1/sales/{second}/items", {"product_id": product, "qty": "1"})
        _post(
            client,
            token,
            f"/api/v1/sales/{second}/confirm",
            {"paid_amount": "1000", "method": "wave"},
        )
        # Retour d'un sac de la vente 1 (1 500 F), sans remboursement encore.
        item = client.get(f"/api/v1/sales/{first}", headers=auth_headers(token)).json()["items"][0]
        _post(
            client,
            token,
            f"/api/v1/sales/{first}/returns",
            {"lines": [{"sale_item_id": item["id"], "qty": "1"}], "reason": "Abîmé"},
        )
        # Dépense payée : loyer 20 000 F en espèces.
        rent = _post(
            client, token, "/api/v1/expense-categories", {"name": "Loyer", "kind": "fixed"}
        )
        _post(
            client,
            token,
            "/api/v1/expenses",
            {
                "category_id": rent["id"],
                "label": "Loyer de novembre",
                "amount": "20000.00",
                "spent_at": today.isoformat(),
                "payment": {"method": "cash"},
            },
        )
        # Dette fournisseur saisie : 45 000 F.
        _post(
            client,
            token,
            "/api/v1/debts",
            {"party_type": "supplier", "supplier_id": supplier, "principal": "45000.00"},
        )
    return Shop(company, token, today)


@pytest.fixture
def token(api_client: TestClient, shop: Shop) -> str:
    return login_token(api_client, shop.company)


def _build(
    client: TestClient,
    token: str,
    enqueued: list[tuple[str, dict[str, Any]]],
    kind: str,
    first: date,
    last: date,
) -> bytes:
    requested = client.post(
        "/api/v1/exports/pdf",
        headers=write_headers(token),
        json={"kind": kind, "date_from": first.isoformat(), "date_to": last.isoformat()},
    )
    assert requested.status_code == 202, requested.text
    assert requested.json()["format"] == "pdf"
    [(_, kwargs)] = [call for call in enqueued if call[0] == "exports.build_sales"]
    assert export_tasks.build_sales(**kwargs) == "ready"
    export_id = requested.json()["id"]
    listed = client.get("/api/v1/exports", headers=auth_headers(token)).json()["items"]
    assert export_id in [row["id"] for row in listed], "le PDF arrive dans Réglages → Fichiers"
    downloaded = client.get(f"/api/v1/exports/{export_id}/file", headers=auth_headers(token))
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-type"] == "application/pdf"
    assert downloaded.headers["cache-control"] == "no-store"
    return downloaded.content


# --------------------------------------------------------------------------- ventes


def test_sales_pdf_matches_the_screen_and_the_excel(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
) -> None:
    text = _text(_build(api_client, token, enqueued, "sales", shop.today, shop.today))
    for expected in ("Boutique Compta", "Rue 10, Dakar", "NINEA 0099887", "Ventes", "Awa Ndiaye"):
        assert expected in text, expected
    assert "Document généré par CoGes" in text
    assert "Page 1/" in text

    # Écran : les totaux par jour de la liste des ventes.
    days = api_client.get(
        "/api/v1/sales/day-totals",
        headers=auth_headers(token),
        # Bornes du jour, à l'heure de Dakar (UTC+0), comme les envoie l'écran.
        params={
            "date_from": f"{shop.today.isoformat()}T00:00:00+00:00",
            "date_to": f"{shop.today.isoformat()}T23:59:59.999999+00:00",
        },
    ).json()["items"]
    screen_total = sum(Decimal(day["total"]) for day in days)
    assert screen_total == Decimal("4500.00")
    assert f"Total des ventes\n{_f(screen_total)}" in text or _f(screen_total) in text
    # Excel : la même période, la même somme des totaux et du payé.
    before = len(enqueued)
    excel = api_client.post(
        "/api/v1/exports/sales",
        headers=write_headers(token),
        json={
            "date_from": shop.today.isoformat(),
            "date_to": shop.today.isoformat(),
            "format": "csv",
        },
    ).json()
    [(_, kwargs)] = [call for call in enqueued[before:] if call[0] == "exports.build_sales"]
    export_tasks.build_sales(**kwargs)
    rows = list(
        csv.reader(
            io.StringIO(
                api_client.get(
                    f"/api/v1/exports/{excel['id']}/file", headers=auth_headers(token)
                ).content.decode("utf-8-sig")
            ),
            delimiter=";",
        )
    )[1:]
    confirmed = [row for row in rows if row[2] != "Annulée"]

    def number(cell: str) -> Decimal:
        return Decimal(cell.replace("\u202f", "").replace(" ", "").replace(",", ".") or "0")

    assert sum(number(row[7]) for row in confirmed) == screen_total
    paid = sum(number(row[8]) for row in confirmed)
    returned = sum(number(row[9]) for row in confirmed)
    assert paid == Decimal("4000.00") and returned == Decimal("1500.00")
    for label, value in (
        ("Payé", paid),
        ("Retours", -returned),
        ("Total net", screen_total - returned),
        ("Reste dû", Decimal("500")),
    ):
        assert f"{label}\n{_f(value)}" in text, (label, text)
    assert "Espèces" in text and "Wave" in text and "À crédit" not in text


def test_an_empty_period_gives_a_document_with_zeros(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
) -> None:
    past = shop.today - timedelta(days=200)
    text = _text(_build(api_client, token, enqueued, "sales", past, past))
    assert "Aucune vente sur la période." in text
    assert "Total des ventes\n0 F" in text


# --------------------------------------------------------------------------- caisse


def test_cash_pdf_matches_the_money_screen(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
) -> None:
    text = _text(_build(api_client, token, enqueued, "cash", shop.today, shop.today))
    money = api_client.get(
        "/api/v1/analytics/money",
        headers=auth_headers(token),
        params={"from": shop.today.isoformat(), "to": shop.today.isoformat()},
    ).json()
    assert Decimal(money["cash_in"]) == Decimal("4000.00")
    assert Decimal(money["cash_out"]) == Decimal("20000.00")
    assert f"Entrées\n{_f(money['cash_in'])}" in text
    assert f"Sorties\n-{_f(money['cash_out'])}" in text, text
    assert f"Solde de début\n{_f('0')}" in text
    assert f"Solde de fin\n{_f(money['net_cash'])}" in text
    assert "Vente n° 1" in text and "Dépense" in text and "Loyer de novembre" in text
    assert "Journal de caisse" in text


def test_cash_opening_balance_carries_the_days_before(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
) -> None:
    tomorrow = shop.today + timedelta(days=1)
    text = _text(_build(api_client, token, enqueued, "cash", tomorrow, tomorrow))
    assert f"Solde de début\n{_f('-16000')}" in text, text
    assert "Aucune entrée ni sortie d'argent sur la période." in text


# ---------------------------------------------------------------- stock, dépenses, dettes


def test_stock_pdf_matches_the_stock_screen(api_client: TestClient, token: str, shop: Shop) -> None:
    response = api_client.get("/api/v1/analytics/stock/pdf", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "Stock-" in response.headers["content-disposition"]
    text = _text(response.content)
    summary = api_client.get("/api/v1/inventory/stock/summary", headers=auth_headers(token)).json()
    assert (
        f"Valeur totale du stock\n{_f(summary['stock_value'])}"
        in text.replace("Valeur totale du stock\n\n\n\n", "Valeur totale du stock\n")
        or _f(summary["stock_value"]) in text
    )
    assert "Riz parfumé" in text and "Épicerie" in text and "48 sacs" in text
    assert "État du stock" in text


def test_expenses_pdf_matches_the_expenses_screen(
    api_client: TestClient, token: str, shop: Shop
) -> None:
    params = {"from": shop.today.isoformat(), "to": shop.today.isoformat()}
    response = api_client.get(
        "/api/v1/analytics/expenses/pdf", headers=auth_headers(token), params=params
    )
    assert response.status_code == 200, response.text
    text = _text(response.content)
    screen = api_client.get(
        "/api/v1/analytics/expenses-summary", headers=auth_headers(token), params=params
    ).json()
    assert Decimal(screen["total"]) == Decimal("20000.00")
    assert f"Total général\n{_f(screen['total'])}" in text
    assert "Loyer" in text and "Loyer de novembre" in text


def test_debts_pdf_matches_the_money_cards(api_client: TestClient, token: str, shop: Shop) -> None:
    response = api_client.get("/api/v1/analytics/debts/pdf", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    text = _text(response.content)
    money = api_client.get(
        "/api/v1/analytics/money?period=today", headers=auth_headers(token)
    ).json()
    assert Decimal(money["receivables"]["total"]) == Decimal("500.00")
    assert Decimal(money["payables"]["total"]) == Decimal("45000.00")
    assert "Awa Ndiaye" in text and "Grossiste Fall" in text
    assert _f(money["receivables"]["total"]) in text
    assert _f(money["payables"]["total"]) in text
    # Les en-têtes des tranches passent sur deux lignes dans leur colonne étroite.
    flat = " ".join(text.split())
    assert "0 À 30 JOURS" in flat and "PLUS DE 90 JOURS" in flat


@pytest.mark.parametrize(
    ("days", "bucket"),
    [(0, 0), (30, 0), (31, 1), (60, 1), (61, 2), (90, 2), (91, 3), (400, 3)],
)
def test_aging_buckets_at_their_bounds(days: int, bucket: int) -> None:
    today = date(2026, 11, 4)
    assert aging_bucket(today - timedelta(days=days), today) == bucket


# ------------------------------------------------------------------------- l'accès


def test_more_than_366_days_is_refused(api_client: TestClient, token: str, shop: Shop) -> None:
    first = shop.today - timedelta(days=366)
    refused = api_client.get(
        "/api/v1/analytics/expenses/pdf",
        headers=auth_headers(token),
        params={"from": first.isoformat(), "to": shop.today.isoformat()},
    )
    assert refused.status_code == 422
    queued = api_client.post(
        "/api/v1/exports/pdf",
        headers=write_headers(token),
        json={"kind": "cash", "date_from": first.isoformat(), "date_to": shop.today.isoformat()},
    )
    assert queued.status_code == 422


def _account_with(
    client: TestClient, manager: str, company: DemoCompany, permissions: list[str]
) -> str:
    role = client.post(
        "/api/v1/roles",
        headers=auth_headers(manager),
        json={"name": f"Rôle {uuid4().hex[:6]}", "permissions": permissions},
    )
    assert role.status_code == 201, role.text
    email = f"r-{uuid4().hex[:8]}@test.sn"
    created = client.post(
        "/api/v1/users",
        headers=auth_headers(manager),
        json={
            "email": email,
            "full_name": "Compte limité",
            "password": TEST_PASSWORD,
            "role_ids": [role.json()["id"]],
        },
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login",
        json={"company_slug": company.slug, "email": email, "password": TEST_PASSWORD},
    )
    return str(login.json()["access_token"])


def test_a_missing_read_or_export_right_is_refused(
    api_client: TestClient, token: str, shop: Shop
) -> None:
    reader = _account_with(api_client, token, shop.company, ["inventory:read", "debts:read"])
    assert (
        api_client.get("/api/v1/analytics/stock/pdf", headers=auth_headers(reader)).status_code
        == 403
    )
    assert (
        api_client.get("/api/v1/analytics/debts/pdf", headers=auth_headers(reader)).status_code
        == 403
    )
    exporter = _account_with(api_client, token, shop.company, ["analytics:export"])
    assert (
        api_client.get("/api/v1/analytics/stock/pdf", headers=auth_headers(exporter)).status_code
        == 403
    )
    both = _account_with(api_client, token, shop.company, ["inventory:read", "analytics:export"])
    assert (
        api_client.get("/api/v1/analytics/stock/pdf", headers=auth_headers(both)).status_code == 200
    )
    refused = api_client.post(
        "/api/v1/exports/pdf",
        headers=write_headers(both),
        json={
            "kind": "sales",
            "date_from": shop.today.isoformat(),
            "date_to": shop.today.isoformat(),
        },
    )
    assert refused.status_code == 403, "les ventes exigent sales:read et sales:export"


def test_a_pdf_file_is_seen_only_with_its_rights(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
) -> None:
    """Un rôle qui n'exporte que des tableurs ne voit pas le journal de caisse (404)."""
    requested = _post(
        api_client,
        token,
        "/api/v1/exports/pdf",
        {"kind": "cash", "date_from": shop.today.isoformat(), "date_to": shop.today.isoformat()},
    )
    spreadsheets = _account_with(api_client, token, shop.company, ["importexport:export"])
    listed = api_client.get("/api/v1/exports", headers=auth_headers(spreadsheets)).json()["items"]
    assert requested["id"] not in [row["id"] for row in listed]
    hidden = api_client.get(
        f"/api/v1/exports/{requested['id']}/file", headers=auth_headers(spreadsheets)
    )
    assert hidden.status_code == 404
    nobody = _account_with(api_client, token, shop.company, ["company:read"])
    assert api_client.get("/api/v1/exports", headers=auth_headers(nobody)).status_code == 403


def test_another_company_sees_nothing_of_this_one(
    api_client: TestClient,
    token: str,
    shop: Shop,
    beta_token: str,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
) -> None:
    requested = _post(
        api_client,
        token,
        "/api/v1/exports/pdf",
        {"kind": "sales", "date_from": shop.today.isoformat(), "date_to": shop.today.isoformat()},
    )
    other = api_client.get(
        f"/api/v1/exports/{requested['id']}/file", headers=auth_headers(beta_token)
    )
    assert other.status_code == 404
    for path in ("/api/v1/analytics/stock/pdf", "/api/v1/analytics/debts/pdf"):
        text = _text(api_client.get(path, headers=auth_headers(beta_token)).content)
        assert "Boutique Compta" not in text and "Awa Ndiaye" not in text
        assert "Grossiste Fall" not in text and "Riz parfumé" not in text


def test_the_history_tells_a_pdf(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
) -> None:
    _build(api_client, token, enqueued, "cash", shop.today, shop.today)
    sentences = [
        line["sentence"]
        for line in api_client.get("/api/v1/analytics/history", headers=auth_headers(token)).json()[
            "items"
        ]
    ]
    assert any("a préparé un document PDF" in s for s in sentences), sentences
