# ruff: noqa: F811  (fixtures du module voisin, reprises par leur nom)
"""Exports PDF pour le comptable : limites et lecture figée (ADR 0114, corrections avant
fusion du 2026-11-05).

- ventes et caisse plafonnées, refus clair dans Réglages → Fichiers ;
- le worker lit dans **une** transaction `READ ONLY REPEATABLE READ` : une vente
  confirmée pendant la génération n'entre ni dans le détail ni dans les totaux ;
- stock, dépenses et dettes : immédiats sous le plafond, par la file d'exports au-delà ;
- le worker ne réessaie que si la demande n'est pas encore visible ;
- le contexte du worker (sans permissions) ne masque rien de ce que l'écran montre.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.errors import NotFoundError
from app.core.tenancy import TenantContext
from app.modules.analytics import reports
from app.workers.tasks import exports as export_tasks
from tests.conftest import auth_headers, write_headers
from tests.integration.test_accountant_pdf import (  # noqa: F401  (fixtures)
    Shop,
    _post,
    _text,
    enqueued,
    shop,
    token,
)

pytestmark = pytest.mark.integration


def _request(
    client: TestClient, token: str, kind: str, **period: str
) -> tuple[str, dict[str, Any]]:
    response = client.post(
        "/api/v1/exports/pdf", headers=write_headers(token), json={"kind": kind, **period}
    )
    assert response.status_code == 202, response.text
    return response.json()["id"], response.json()


def _task(enqueued: list[tuple[str, dict[str, Any]]], export_id: str) -> dict[str, Any]:
    [kwargs] = [
        kwargs
        for name, kwargs in enqueued
        if name == "exports.build_sales" and kwargs["export_id"] == export_id
    ]
    return kwargs


def _export(client: TestClient, token: str, export_id: str) -> dict[str, Any]:
    items = client.get("/api/v1/exports", headers=auth_headers(token)).json()["items"]
    [row] = [row for row in items if row["id"] == export_id]
    return dict(row)


def _day(shop: Shop) -> dict[str, str]:
    return {"date_from": shop.today.isoformat(), "date_to": shop.today.isoformat()}


def _sale(client: TestClient, token: str, price: str = "2000") -> None:
    product = _post(client, token, "/api/v1/products", {"name": "Huile", "unit_price": price})["id"]
    _post(
        client,
        token,
        "/api/v1/inventory/movements",
        {"product_id": product, "type": "initial", "qty_delta": "5", "unit_cost": "900"},
    )
    sale = _post(client, token, "/api/v1/sales", {})["id"]
    _post(client, token, f"/api/v1/sales/{sale}/items", {"product_id": product, "qty": "1"})
    _post(client, token, f"/api/v1/sales/{sale}/confirm", {"paid_amount": price, "method": "cash"})


# ------------------------------------------------------------------------ plafonds


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("sales", "Plus de 1 ventes sur la période : choisissez une période plus courte."),
        (
            "cash",
            "Plus de 1 lignes de caisse sur la période : choisissez une période plus courte.",
        ),
    ],
)
def test_beyond_the_cap_the_file_fails_with_a_clear_message(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    message: str,
) -> None:
    monkeypatch.setattr(reports, "MAX_DOCUMENT_LINES", 1)
    export_id, _ = _request(api_client, token, kind, **_day(shop))
    assert export_tasks.build_sales(**_task(enqueued, export_id)) == "failed"
    row = _export(api_client, token, export_id)
    assert row["status"] == "failed"
    assert row["error"] == message


def test_the_sales_cap_is_20000_like_the_cash() -> None:
    assert reports.MAX_DOCUMENT_LINES == 20_000
    assert reports.MAX_IMMEDIATE_LINES == 1_000


# ------------------------------------------------------------- nouvelle tentative


def test_only_a_not_yet_visible_request_is_retried(
    workers_bound_to_test_database: None, shop: Shop
) -> None:
    """Demande absente (pas encore validée par l'API) : la tâche réessaie ; appelée
    directement, Celery relève l'erreur au lieu de replanifier."""
    from uuid import uuid4

    from app.modules.importexport.service import ExportNotVisibleError

    me_id = str(shop.company.company_id)
    with pytest.raises(ExportNotVisibleError):
        export_tasks.build_sales(company_id=me_id, user_id=str(uuid4()), export_id=str(uuid4()))


def test_another_not_found_fails_the_export_without_retrying(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_id, _ = _request(api_client, token, "sales", **_day(shop))

    def missing(*args: Any, **kwargs: Any) -> Any:
        raise NotFoundError("Entreprise introuvable.")

    monkeypatch.setattr(reports, "masthead", missing)
    assert export_tasks.build_sales(**_task(enqueued, export_id)) == "failed"
    row = _export(api_client, token, export_id)
    assert row["status"] == "failed"
    # Réglages → Fichiers montre une phrase, jamais le nom de l'erreur.
    assert row["error"] == export_tasks.EXPORT_CRASHED


# --------------------------------------------- stock, dépenses, dettes par la file

IMMEDIATE = [
    ("stock", "/api/v1/analytics/stock/pdf", False),
    ("expenses", "/api/v1/analytics/expenses/pdf", True),
    ("debts", "/api/v1/analytics/debts/pdf", False),
]


def _comparable(content: bytes) -> str:
    """Le texte d'un PDF sans l'heure d'édition (le worker passe une minute après)."""
    return re.sub(r"Édité le .*", "", _text(content))


@pytest.mark.parametrize(("kind", "path", "dated"), IMMEDIATE)
def test_beyond_the_immediate_cap_the_document_goes_through_the_queue(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    path: str,
    dated: bool,
) -> None:
    params = {"from": shop.today.isoformat(), "to": shop.today.isoformat()} if dated else {}
    immediate = api_client.get(path, headers=auth_headers(token), params=params)
    assert immediate.status_code == 200, immediate.text

    monkeypatch.setattr(reports, "MAX_IMMEDIATE_LINES", 0)
    refused = api_client.get(path, headers=auth_headers(token), params=params)
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "report_too_large"
    assert error["details"]["kind"] == kind
    assert error["details"]["limit"] == 0
    assert error["details"]["rows"] >= 1
    assert "Réglages → Fichiers" in error["message"]

    export_id, created = _request(api_client, token, kind, **(_day(shop) if dated else {}))
    assert created["kind"] == kind and created["format"] == "pdf"
    assert export_tasks.build_sales(**_task(enqueued, export_id)) == "ready"
    queued = api_client.get(f"/api/v1/exports/{export_id}/file", headers=auth_headers(token))
    assert queued.status_code == 200
    # Le PDF de la file dit exactement ce que dit le PDF immédiat (et donc l'écran).
    assert _comparable(queued.content) == _comparable(immediate.content)


def test_a_dated_document_needs_its_period_and_an_undated_one_refuses_it(
    api_client: TestClient, token: str, shop: Shop
) -> None:
    for kind in ("sales", "cash", "expenses"):
        missing = api_client.post(
            "/api/v1/exports/pdf", headers=write_headers(token), json={"kind": kind}
        )
        assert missing.status_code == 422, (kind, missing.text)
    for kind in ("stock", "debts"):
        dated = api_client.post(
            "/api/v1/exports/pdf",
            headers=write_headers(token),
            json={"kind": kind, **_day(shop)},
        )
        assert dated.status_code == 422, (kind, dated.text)


# ------------------------------------------------------------- contexte du worker


@pytest.mark.parametrize("kind", ["sales", "cash", "stock", "expenses", "debts"])
def test_the_worker_context_hides_nothing_the_screen_shows(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    period = _day(shop) if kind in ("sales", "cash", "expenses") else {}
    export_id, _ = _request(api_client, token, kind, **period)

    def forbidden(self: TenantContext, code: str) -> bool:
        raise AssertionError(f"un rapport a consulté la permission {code!r}")

    with monkeypatch.context() as patched:
        patched.setattr(TenantContext, "has_permission", forbidden)
        assert export_tasks.build_sales(**_task(enqueued, export_id)) == "ready"
    built = api_client.get(f"/api/v1/exports/{export_id}/file", headers=auth_headers(token))
    text = _text(built.content)
    # Ce que l'écran du gérant montre pour la même période.
    money = api_client.get(
        "/api/v1/analytics/money",
        headers=auth_headers(token),
        params={"from": shop.today.isoformat(), "to": shop.today.isoformat()},
    ).json()
    expected = {
        "sales": ["Awa Ndiaye", "4 500 F", "Espèces", "Wave"],
        "cash": ["4 000 F", "-20 000 F", "Loyer de novembre", "Awa Ndiaye"],
        "stock": ["Riz parfumé", "48 sacs", "Épicerie"],
        "expenses": ["Loyer de novembre", "20 000 F"],
        "debts": ["Awa Ndiaye", "Grossiste Fall", "500 F", "45 000 F"],
    }[kind]
    for value in expected:
        assert value in text, (kind, value, text)
    if kind == "cash":
        assert Decimal(money["cash_in"]) == Decimal("4000.00")


# ------------------------------------------------------------------- lecture figée
# En dernier : la vente ajoutée pendant la génération reste dans la boutique du module.


def test_a_sale_confirmed_during_the_build_enters_neither_lines_nor_totals(
    api_client: TestClient,
    concurrent_session_factory: sessionmaker[Any],
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une page par vente : la vente confirmée après la première page décalerait la
    suivante (doublon, total faux) sans instantané unique."""
    export_id, _ = _request(api_client, token, "sales", **_day(shop))
    monkeypatch.setattr(reports, "_PAGE", 1)
    original = reports.sales_service.list_sales
    pages: list[int] = []

    def list_sales_then_sell(*args: Any, **kwargs: Any) -> Any:
        found = original(*args, **kwargs)
        if kwargs.get("status") == "confirmed" and kwargs.get("page_size") == 1:
            pages.append(kwargs["page"])
            if kwargs["page"] == 1:
                # Le pool de la suite n'a qu'une connexion, tenue par le worker : la
                # vente passe par un autre pool, dans sa propre transaction validée.
                with monkeypatch.context() as other:
                    for target in (
                        "app.core.tenancy.get_session_factory",
                        "app.modules.auth.repository.get_session_factory",
                    ):
                        other.setattr(target, lambda: concurrent_session_factory)
                    _sale(api_client, token, price="7777")
        return found

    monkeypatch.setattr(reports.sales_service, "list_sales", list_sales_then_sell)
    assert export_tasks.build_sales(**_task(enqueued, export_id)) == "ready", _export(
        api_client, token, export_id
    )["error"]
    text = _text(
        api_client.get(f"/api/v1/exports/{export_id}/file", headers=auth_headers(token)).content
    )
    assert "2 ventes" in text, text
    assert "7 777" not in text
    assert "Total des ventes\n4 500 F" in text, text


def test_the_worker_reads_in_a_read_only_repeatable_read_transaction(
    api_client: TestClient,
    token: str,
    shop: Shop,
    enqueued: list[tuple[str, dict[str, Any]]],
    workers_bound_to_test_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import text

    seen: list[tuple[str, str]] = []
    original = reports.masthead

    def spy(session: Any, ctx: TenantContext, **period: Any) -> Any:
        seen.append(
            (
                session.execute(text("SHOW transaction_isolation")).scalar_one(),
                session.execute(text("SHOW transaction_read_only")).scalar_one(),
            )
        )
        return original(session, ctx, **period)

    monkeypatch.setattr(reports, "masthead", spy)
    for kind, period in (("sales", _day(shop)), ("cash", _day(shop))):
        export_id, _ = _request(api_client, token, kind, **period)
        assert export_tasks.build_sales(**_task(enqueued, export_id)) == "ready"
    assert seen == [("repeatable read", "on")] * 2
