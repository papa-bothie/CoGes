"""Corriger une vente : « Annuler et refaire » pendant 10 minutes (prompt 36, bloc R).

Le geste annule la vente encaissée — paiements de la confirmation contre-passés,
stock rendu, dette fermée — et ouvre un brouillon identique, relié à elle par
`corrects_sale_id`. La personne corrige puis réencaisse comme toute vente.

Ce qui compte d'abord : la caisse du jour. Une vente corrigée puis réencaissée ne
laisse en caisse que le second encaissement, jamais les deux, jamais aucun.

Une entreprise à part : les chiffres de caisse du jour et les invariants ne sont
pas pollués par les autres fichiers de tests.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.events.inbox import Event
from app.core.events.types import EventType
from app.core.tenancy import TenantContext, tenant_transaction
from app.main import app
from app.modules.sales import service as sales_service
from app.workers.tasks.notifications import on_sale_cancelled
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    lift_user_cap,
    login_token,
    read_scalar_in_tenant,
    write_headers,
)
from tests.helpers.invariants import assert_consistent
from tests.integration.test_sales_api import (
    _add_line,
    _draft,
    _make_customer,
    _make_product,
    _stock_of,
    _token_for_role,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def shop(app_bound_to_test_database: None, owner_engine: Engine) -> DemoCompany:
    company = _create_demo_company(f"correction-{uuid4().hex[:6]}")
    lift_user_cap(owner_engine, company.company_id)
    return company


@pytest.fixture
def token(api_client: TestClient, shop: DemoCompany) -> str:
    return login_token(api_client, shop)


# ------------------------------------------------------------------ outils


def read_row_in_tenant(
    session_factory: sessionmaker[Any], company_id: UUID, sql: str, params: dict[str, Any]
) -> Any:
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        return session.execute(text(sql), params).one()


def _sale(
    client: TestClient,
    token: str,
    *,
    paid: str,
    qty: str = "2",
    customer: bool = False,
    product_id: str | None = None,
) -> dict[str, Any]:
    """Vente confirmée d'un article à 1 500 (coût 1 000), `qty` unités, `paid` encaissé."""
    product = product_id or _make_product(client, token)
    customer_id = _make_customer(client, token) if customer else None
    sale_id = _draft(client, token, **({"customer_id": customer_id} if customer_id else {}))
    added = _add_line(client, token, sale_id, product, qty=qty)
    assert added.status_code == 201, added.text
    confirmed = client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(token),
        json={"paid_amount": paid, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return {**confirmed.json(), "product_id": product}


def _correct(client: TestClient, token: str, sale_id: str, key: str | None = None) -> Any:
    return client.post(
        f"/api/v1/sales/{sale_id}/correct", headers=write_headers(token, key), json={}
    )


def _detail(client: TestClient, token: str, sale_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return dict(response.json())


def _cash(client: TestClient, token: str) -> dict[str, Any]:
    response = client.get("/api/v1/analytics/cash", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return dict(response.json())


def _cash_on_hand(client: TestClient, token: str) -> Decimal:
    response = client.get("/api/v1/dashboard", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return Decimal(response.json()["cash_on_hand"])


def _freeze_correction_clock(monkeypatch: pytest.MonkeyPatch, at: datetime) -> None:
    """Le délai se compte à l'heure du serveur : on fige celle du service."""
    monkeypatch.setattr(sales_service, "_correction_now", lambda: at)


# -------------------------------------------- la caisse du jour, d'abord


def test_a_cash_sale_corrected_then_paid_again_leaves_the_day_cash_exact(
    api_client: TestClient, token: str, shop: DemoCompany, owner_engine: Engine
) -> None:
    """3 000 encaissés, corrigés, réencaissés à 1 500 : la caisse gagne 1 500, pas 4 500."""
    cash_before = Decimal(_cash(api_client, token)["net_cash"])
    on_hand_before = _cash_on_hand(api_client, token)

    sale = _sale(api_client, token, paid="3000.00")
    stock_after_sale = _stock_of(api_client, token, sale["product_id"])

    corrected = _correct(api_client, token, sale["id"])
    assert corrected.status_code == 200, corrected.text
    draft = corrected.json()
    assert draft["status"] == "draft"
    assert draft["id"] != sale["id"]
    assert draft["sale_no"] != sale["sale_no"], "le brouillon a son propre numéro"
    assert draft["corrects_sale"]["id"] == sale["id"]
    assert [(i["product_id"], i["qty"]) for i in draft["items"]] == [(sale["product_id"], "2.000")]

    # Après le geste : rien en caisse, le stock est rendu, l'ancienne vente est annulée.
    assert Decimal(_cash(api_client, token)["net_cash"]) == cash_before
    assert _cash_on_hand(api_client, token) == on_hand_before
    assert _stock_of(api_client, token, sale["product_id"]) == stock_after_sale + 2
    old = _detail(api_client, token, sale["id"])
    assert old["status"] == "cancelled"
    assert old["cancel_reason"] == "Corrigée"
    assert old["corrected_by_sale"] == {
        "id": draft["id"],
        "sale_no": draft["sale_no"],
        "status": "draft",
    }
    assert [p["cancelled"] for p in old["payments"] if not p["reversal_of_payment_id"]] == [True]

    # La personne corrige (une seule unité) et réencaisse.
    item_id = draft["items"][0]["id"]
    lowered = api_client.patch(
        f"/api/v1/sales/{draft['id']}/items/{item_id}",
        headers=auth_headers(token),
        json={"qty": "1"},
    )
    assert lowered.status_code == 200, lowered.text
    paid_again = api_client.post(
        f"/api/v1/sales/{draft['id']}/confirm",
        headers=write_headers(token),
        json={"paid_amount": "1500.00", "method": "cash"},
    )
    assert paid_again.status_code == 200, paid_again.text

    assert Decimal(_cash(api_client, token)["net_cash"]) == cash_before + Decimal("1500")
    assert _cash_on_hand(api_client, token) == on_hand_before + Decimal("1500")
    assert _stock_of(api_client, token, sale["product_id"]) == stock_after_sale + 1
    assert _detail(api_client, token, sale["id"])["corrected_by_sale"]["status"] == "confirmed"
    assert_consistent(owner_engine, shop.company_id)


def test_the_cash_journal_marks_both_lines_of_a_correction(
    api_client: TestClient, token: str
) -> None:
    """L'annulation du paiement et le nouvel encaissement sont listés, marqués « correction »."""
    sale = _sale(api_client, token, paid="3000.00")
    draft = _correct(api_client, token, sale["id"]).json()
    confirmed = api_client.post(
        f"/api/v1/sales/{draft['id']}/confirm",
        headers=write_headers(token),
        json={"paid_amount": "3000.00", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    lines = _cash(api_client, token)["lines"]
    old_lines = [line for line in lines if line["sale_id"] == sale["id"]]
    new_lines = [line for line in lines if line["sale_id"] == draft["id"]]

    original = next(line for line in old_lines if not line["is_reversal"])
    reversal = next(line for line in old_lines if line["is_reversal"])
    assert original["cancelled"] is True
    assert original["correction"] is False, "l'encaissement d'origine était normal"
    assert reversal["correction"] is True
    assert reversal["cancel_reason"] == "Corrigée"
    assert [line["correction"] for line in new_lines] == [True]


# ---------------------------------------------------------------- le délai


def test_the_window_is_ten_minutes_by_the_server_clock(
    api_client: TestClient, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert timedelta(minutes=10) == sales_service.CORRECTION_WINDOW

    sale = _sale(api_client, token, paid="3000.00")
    confirmed_at = datetime.fromisoformat(sale["confirmed_at"])

    _freeze_correction_clock(monkeypatch, confirmed_at + timedelta(minutes=7, seconds=5))
    assert _detail(api_client, token, sale["id"])["correction_seconds_left"] == 175

    _freeze_correction_clock(monkeypatch, confirmed_at + timedelta(minutes=10, seconds=1))
    assert _detail(api_client, token, sale["id"])["correction_seconds_left"] is None
    refused = _correct(api_client, token, sale["id"])
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "correction_window_closed"
    assert _detail(api_client, token, sale["id"])["status"] == "confirmed"

    _freeze_correction_clock(monkeypatch, confirmed_at + timedelta(minutes=9, seconds=59))
    assert _correct(api_client, token, sale["id"]).status_code == 200


def test_a_draft_has_no_correction_window(api_client: TestClient, token: str) -> None:
    sale_id = _draft(api_client, token)
    assert _detail(api_client, token, sale_id)["correction_seconds_left"] is None
    refused = _correct(api_client, token, sale_id)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "sale_not_confirmed"


# ------------------------------------------------- payée en partie, à crédit


def test_a_partly_paid_sale_is_corrected_and_its_debt_closed(
    api_client: TestClient, token: str, shop: DemoCompany, owner_engine: Engine
) -> None:
    sale = _sale(api_client, token, paid="1000.00", customer=True)
    assert sale["debt"]["balance"] == "2000.00"
    cash_before = Decimal(_cash(api_client, token)["net_cash"])

    corrected = _correct(api_client, token, sale["id"])
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["customer_id"] == sale["customer_id"]

    old = _detail(api_client, token, sale["id"])
    assert old["status"] == "cancelled"
    assert old["debt"]["status"] == "written_off"
    assert Decimal(_cash(api_client, token)["net_cash"]) == cash_before - Decimal("1000")
    assert_consistent(owner_engine, shop.company_id)


def test_a_credit_sale_is_corrected_without_touching_the_cash(
    api_client: TestClient, token: str
) -> None:
    sale = _sale(api_client, token, paid="0", customer=True)
    cash_before = Decimal(_cash(api_client, token)["net_cash"])

    corrected = _correct(api_client, token, sale["id"])
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["customer_id"] == sale["customer_id"]
    assert _detail(api_client, token, sale["id"])["debt"]["status"] == "written_off"
    assert Decimal(_cash(api_client, token)["net_cash"]) == cash_before


def test_a_changed_price_and_its_reason_are_carried_to_the_draft(
    api_client: TestClient, token: str
) -> None:
    product_id = _make_product(api_client, token)
    sale_id = _draft(api_client, token)
    item_id = _add_line(api_client, token, sale_id, product_id, qty="2", discount="100").json()[
        "id"
    ]
    changed = api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{item_id}",
        headers=auth_headers(token),
        json={"unit_price": "1200.00", "price_reason": "Client fidèle"},
    )
    assert changed.status_code == 200, changed.text
    confirmed = api_client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=write_headers(token),
        json={"paid_amount": "2300.00", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    draft = _correct(api_client, token, sale_id).json()
    line = draft["items"][0]
    assert (line["unit_price"], line["list_price"], line["price_changed"]) == (
        "1200.00",
        "1500.00",
        True,
    )
    assert line["price_reason"] == "Client fidèle"
    assert line["discount"] == "100.00"
    assert draft["total"] == "2300.00"


# ---------------------------------------------------------------- refus


def test_a_sale_with_a_return_is_refused(api_client: TestClient, token: str) -> None:
    sale = _sale(api_client, token, paid="3000.00")
    returned = api_client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=write_headers(token),
        json={"lines": [{"sale_item_id": sale["items"][0]["id"], "qty": "1"}]},
    )
    assert returned.status_code == 201, returned.text

    refused = _correct(api_client, token, sale["id"])
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "sale_has_returns"
    assert "faites plutôt un retour" in error["message"]


def test_a_debt_collected_after_the_sale_is_refused(api_client: TestClient, token: str) -> None:
    sale = _sale(api_client, token, paid="1000.00", customer=True)
    collected = api_client.post(
        "/api/v1/payments",
        headers=write_headers(token),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": "500.00",
            "allocations": [{"debt_id": sale["debt"]["id"], "amount": "500.00"}],
        },
    )
    assert collected.status_code == 201, collected.text

    refused = _correct(api_client, token, sale["id"])
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "sale_paid_after_confirmation"
    assert _detail(api_client, token, sale["id"])["status"] == "confirmed"


def test_a_cancelled_sale_is_refused(api_client: TestClient, token: str) -> None:
    sale = _sale(api_client, token, paid="0", customer=True)
    cancelled = api_client.post(
        f"/api/v1/sales/{sale['id']}/cancel",
        headers=auth_headers(token),
        json={"reason": "Erreur de saisie"},
    )
    assert cancelled.status_code == 200, cancelled.text

    refused = _correct(api_client, token, sale["id"])
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "sale_already_cancelled"


# ----------------------------------------------------------------- droits


def test_a_seller_corrects_a_colleagues_sale(
    api_client: TestClient, token: str, shop: DemoCompany
) -> None:
    """Toute personne qui peut vendre, pas seulement celle qui a encaissé."""
    sale = _sale(api_client, token, paid="3000.00")
    seller = _token_for_role(api_client, token, shop, "vendeur")

    corrected = _correct(api_client, seller, sale["id"])
    assert corrected.status_code == 200, corrected.text
    assert _detail(api_client, seller, sale["id"])["correction_seconds_left"] is None


def test_a_seller_still_cannot_cancel(
    api_client: TestClient, token: str, shop: DemoCompany
) -> None:
    """Corriger ne donne pas le droit général d'annuler."""
    sale = _sale(api_client, token, paid="0", customer=True)
    seller = _token_for_role(api_client, token, shop, "vendeur")
    refused = api_client.post(
        f"/api/v1/sales/{sale['id']}/cancel",
        headers=auth_headers(seller),
        json={"reason": "Erreur"},
    )
    assert refused.status_code == 403, refused.text


def test_an_accountant_cannot_correct(
    api_client: TestClient, token: str, shop: DemoCompany
) -> None:
    sale = _sale(api_client, token, paid="3000.00")
    accountant = _token_for_role(api_client, token, shop, "comptable")

    refused = _correct(api_client, accountant, sale["id"])
    assert refused.status_code == 403, refused.text
    assert _detail(api_client, token, sale["id"])["status"] == "confirmed"


def test_another_company_gets_404(api_client: TestClient, token: str, beta_token: str) -> None:
    sale = _sale(api_client, token, paid="3000.00")
    refused = _correct(api_client, beta_token, sale["id"])
    assert refused.status_code == 404, refused.text
    assert _detail(api_client, token, sale["id"])["status"] == "confirmed"


# ------------------------------------------------- double appui, deux personnes


def test_a_double_tap_corrects_once(api_client: TestClient, token: str) -> None:
    sale = _sale(api_client, token, paid="3000.00")
    key = uuid4().hex
    first = _correct(api_client, token, sale["id"], key)
    second = _correct(api_client, token, sale["id"], key)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_the_second_person_is_told_it_is_already_corrected(
    api_client: TestClient, token: str
) -> None:
    sale = _sale(api_client, token, paid="3000.00")
    draft = _correct(api_client, token, sale["id"]).json()

    refused = _correct(api_client, token, sale["id"])
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "sale_already_corrected"
    assert error["details"]["draft_id"] == draft["id"]
    assert error["details"]["draft_sale_no"] == draft["sale_no"]


def _race(calls: list[Callable[[TestClient], Any]]) -> list[Any]:
    clients = [TestClient(app, base_url=TEST_BASE_URL) for _ in calls]
    for client in clients:
        client.__enter__()
    try:
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return list(pool.map(lambda pair: pair[0](pair[1]), zip(calls, clients, strict=True)))
    finally:
        for client in clients:
            client.__exit__(None, None, None)


def test_two_people_at_once_make_a_single_draft(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    owner_engine: Engine,
    session_factory: sessionmaker[Any],
) -> None:
    sale = _sale(api_client, token, paid="3000.00")
    on_hand_before = _cash_on_hand(api_client, token)

    def attempt(client: TestClient) -> Any:
        return _correct(client, token, sale["id"])

    answers = _race([attempt, attempt])
    codes = sorted(answer.status_code for answer in answers)
    assert codes == [200, 409], [answer.text for answer in answers]
    loser = next(answer for answer in answers if answer.status_code == 409)
    assert loser.json()["error"]["code"] in ("sale_already_corrected", "concurrent_update")

    drafts = read_scalar_in_tenant(
        session_factory,
        shop.company_id,
        "SELECT count(*) FROM sales WHERE corrects_sale_id = :id",
        {"id": sale["id"]},
    )
    assert drafts == 1
    assert _cash_on_hand(api_client, token) == on_hand_before - Decimal("3000"), (
        "un seul encaissement contre-passé"
    )
    assert_consistent(owner_engine, shop.company_id)


# ------------------------------------------------------- trace et alerte


def test_the_correction_is_audited_and_announced(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    sale = _sale(api_client, token, paid="3000.00")
    draft = _correct(api_client, token, sale["id"]).json()

    audited = read_scalar_in_tenant(
        session_factory,
        shop.company_id,
        """
        SELECT diff -> 'after' -> 'correction'
          FROM audit_logs
         WHERE entity_table = 'sales' AND entity_id = :id AND action = 'cancel'
        """,
        {"id": sale["id"]},
    )
    assert audited["draft_id"] == draft["id"]
    assert audited["draft_sale_no"] == draft["sale_no"]

    event_id, payload = read_row_in_tenant(
        session_factory,
        shop.company_id,
        """
        SELECT id, payload FROM business_events
         WHERE event_type = 'sale.cancelled' AND aggregate_id = :id
        """,
        {"id": sale["id"]},
    )
    assert payload["reason"] == "Corrigée"
    assert payload["corrected"] is True
    assert payload["corrected_by_user_id"] == str(shop.manager_id)
    payments_cancelled = read_scalar_in_tenant(
        session_factory,
        shop.company_id,
        """
        SELECT count(*) FROM business_events
         WHERE event_type = 'payment.cancelled' AND payload ->> 'sale_id' = :id
        """,
        {"id": sale["id"]},
    )
    assert payments_cancelled == 1

    # L'alerte existante dit qui a corrigé : une correction n'est jamais silencieuse.
    on_sale_cancelled(
        **Event(
            id=event_id,
            company_id=shop.company_id,
            event_type=EventType.SALE_CANCELLED,
            aggregate_type="sale",
            aggregate_id=UUID(sale["id"]),
            payload=payload,
            occurred_at=datetime.now(UTC),
        ).as_message()
    )
    feed = api_client.get(
        "/api/v1/notifications?page_size=100", headers=auth_headers(token)
    ).json()["items"]
    alert = next(item for item in feed if item["data"].get("sale_id") == sale["id"])
    manager_name = api_client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["user"][
        "full_name"
    ]
    assert alert["body"] == f"Corrigée par {manager_name}"
