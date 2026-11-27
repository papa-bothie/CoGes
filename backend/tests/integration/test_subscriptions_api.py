"""Abonnements vus par l'administration (ADR 0091).

Lecture par les deux profils, écritures par l'administrateur seul ; une descente d'offre
trop petite pour les comptes actifs est refusée avec le nombre à désactiver ; un paiement
déclaré active, prolonge et réactive, une fois par clé ; tout geste est au journal
critique, et un COMMIT refusé ne laisse rien.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core import queue
from app.main import app
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
)
from tests.integration.billing_harness import set_subscription, subscription_row
from tests.integration.platform_harness import (
    PlatformAccount,
    create_platform_account,
    failing_platform_commit,
    platform_login,
)

PLAN_KEYS = {
    "id",
    "code",
    "name",
    "price_fcfa",
    "semiannual_price_fcfa",
    "annual_price_fcfa",
    "max_users",
    "features",
    "is_orderable",
}
DETAIL_KEYS = {
    "company_id",
    "plan",
    "status",
    "trial_ends_at",
    "started_at",
    "current_period_end",
    "active_users",
    "is_license",
    "extra_features",
    "max_users_override",
    "max_users",
    "reminder_stage",
    "reminder_for_end",
    "reminder_at",
    "payments",
    "payments_total",
}


@pytest.fixture
def client(platform_bound_to_test_database: None) -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def administrator(platform_bound_to_test_database: None) -> PlatformAccount:
    return create_platform_account("administrator")


@pytest.fixture
def admin_headers(client: TestClient, administrator: PlatformAccount) -> dict[str, str]:
    return auth_headers(platform_login(client, administrator))


@pytest.fixture
def shop(platform_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"abonne-{uuid4().hex[:8]}")


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def _record(task_name: str, **kwargs: Any) -> bool:
        calls.append((task_name, kwargs))
        return True

    monkeypatch.setattr(queue, "enqueue", _record)
    return calls


def _url(company_id: UUID, tail: str = "subscription") -> str:
    return f"/api/v1/platform/companies/{company_id}/{tail}"


def _pay(
    client: TestClient, headers: dict[str, str], company_id: UUID, key: str, **body: Any
) -> Any:
    payload = {
        "amount_fcfa": "4900",
        "paid_at": datetime.now(UTC).isoformat(),
        "method": "wave",
        "note": "Reçu par Wave",
        **body,
    }
    return client.post(
        _url(company_id, "payments"),
        headers={**headers, "Idempotency-Key": key},
        json=payload,
    )


def _audit_rows(platform_session_factory: sessionmaker[Any], company_id: UUID) -> list[Any]:
    with platform_session_factory.begin() as session:
        return list(
            session.execute(
                text(
                    "SELECT entity_table, action, diff FROM platform_audit_logs "
                    "WHERE target_company_id = :id ORDER BY id"
                ),
                {"id": company_id},
            )
        )


# ---------------------------------------------------------------------- lecture


def test_the_three_offers_are_seeded(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Pro et Business en vente, Premium sur devis (ADR 0132) ; codes inchangés."""
    response = client.get("/api/v1/platform/plans", headers=admin_headers)
    assert response.status_code == 200
    assert all(set(plan) == PLAN_KEYS for plan in response.json())
    seeded = {plan["code"]: plan for plan in response.json() if plan["code"] != "sur_devis"}
    assert {
        code: (
            plan["name"],
            plan["price_fcfa"],
            plan["semiannual_price_fcfa"],
            plan["annual_price_fcfa"],
            plan["max_users"],
            plan["is_orderable"],
        )
        for code, plan in seeded.items()
    } == {
        "starter": ("Pro", "4900.00", "29400.00", "52920.00", 3, True),
        "business": ("Business", "9900.00", "59400.00", "106920.00", 7, True),
        "premium": ("Premium", None, None, None, 10, False),
    }


def test_a_new_company_starts_a_30_day_pro_trial(client: TestClient, shop: DemoCompany) -> None:
    support = auth_headers(platform_login(client, create_platform_account("support")))
    response = client.get(_url(shop.company_id), headers=support)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == DETAIL_KEYS
    assert (body["plan"]["code"], body["status"], body["active_users"]) == ("starter", "trial", 1)
    ends = datetime.fromisoformat(body["trial_ends_at"])
    assert abs(ends - datetime.now(UTC) - timedelta(days=30)) < timedelta(minutes=5)
    detail = client.get(f"/api/v1/platform/companies/{shop.company_id}", headers=support)
    assert detail.json()["status"] == "trial"


def test_an_unknown_company_is_404(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert client.get(_url(uuid4()), headers=admin_headers).status_code == 404


# ------------------------------------------------------------- changer d'offre


def test_changing_offer_is_audited_and_leaves_access_alone(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    response = client.patch(
        _url(shop.company_id),
        headers=admin_headers,
        json={"plan_code": "business", "reason": "Le client a choisi Business"},
    )
    assert response.status_code == 200
    assert (response.json()["plan"]["code"], response.json()["status"]) == ("business", "trial")
    [row] = _audit_rows(platform_session_factory, shop.company_id)
    assert (row.entity_table, row.action) == ("subscriptions", "update")
    assert row.diff["before"] == {"plan": "starter", "status": "trial"}
    assert row.diff["after"] == {"plan": "business", "status": "trial"}
    assert enqueued == []


def test_a_downgrade_below_the_active_accounts_says_how_many_to_deactivate(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    set_subscription(platform_session_factory, shop.company_id, plan="business")
    manager = auth_headers(login_token(client, shop))
    for n in range(4):
        created = client.post(
            "/api/v1/users",
            headers=manager,
            json={"full_name": f"Vendeur {n}", "email": f"v{n}-{uuid4().hex[:6]}@test.example"},
        )
        assert created.status_code == 201
    refused = client.patch(
        _url(shop.company_id),
        headers=admin_headers,
        json={"plan_code": "starter", "reason": "Le client veut payer moins"},
    )
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert error["code"] == "plan_downgrade_too_many_users"
    assert error["details"] == {"active_users": 5, "max_users": 3, "to_deactivate": 2}
    assert "Désactivez-en 2" in error["message"]


@pytest.mark.parametrize(
    "body",
    [
        {"plan_code": "sur_devis_inconnu", "reason": "offre absente"},
        {"reason": "rien à changer"},
        {"status": "trial", "reason": "l'essai ne se repose pas"},
    ],
)
def test_impossible_requests_are_422(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany, body: dict[str, Any]
) -> None:
    assert client.patch(_url(shop.company_id), headers=admin_headers, json=body).status_code == 422


def test_suspending_the_subscription_cuts_access_and_tells_the_manager(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    response = client.patch(
        _url(shop.company_id),
        headers=admin_headers,
        json={"status": "suspended", "reason": "Impayé"},
    )
    assert response.status_code == 200
    refused = client.post(
        "/api/v1/auth/login",
        json={"company_slug": shop.slug, "email": shop.email, "password": "mot-de-passe-de-test"},
    )
    assert refused.status_code in (401, 403)
    detail = client.get(f"/api/v1/platform/companies/{shop.company_id}", headers=admin_headers)
    assert detail.json()["status"] == "suspended"
    assert [name for name, _ in enqueued] == ["platform.company_status_changed"]

    past_due = client.patch(
        _url(shop.company_id),
        headers=admin_headers,
        json={"status": "past_due", "reason": "Relance"},
    )
    assert past_due.json()["status"] == "past_due"
    detail = client.get(f"/api/v1/platform/companies/{shop.company_id}", headers=admin_headers)
    assert detail.json()["status"] == "active"


def test_support_reads_but_never_writes(client: TestClient, shop: DemoCompany) -> None:
    support = auth_headers(platform_login(client, create_platform_account("support")))
    assert (
        client.patch(
            _url(shop.company_id), headers=support, json={"status": "suspended", "reason": "non"}
        ).status_code
        == 403
    )
    assert _pay(client, support, shop.company_id, uuid4().hex).status_code == 403


# ------------------------------------------------------------------ paiements


def test_a_payment_activates_extends_and_reactivates(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    set_subscription(platform_session_factory, shop.company_id, status="suspended")
    client.patch(
        f"/api/v1/platform/companies/{shop.company_id}/status",
        headers=admin_headers,
        json={"status": "suspended", "reason": "Fin d'essai"},
    )
    enqueued.clear()

    response = _pay(client, admin_headers, shop.company_id, f"paiement-{uuid4().hex}")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    period_end = datetime.fromisoformat(body["current_period_end"])
    assert timedelta(days=27) < period_end - datetime.now(UTC) < timedelta(days=32)
    assert body["payments_total"] == 1
    [payment] = body["payments"]
    assert (
        payment["amount_fcfa"],
        payment["method"],
        payment["note"],
        payment["period_months"],
    ) == ("4900.00", "wave", "Reçu par Wave", 1)
    detail = client.get(f"/api/v1/platform/companies/{shop.company_id}", headers=admin_headers)
    assert detail.json()["status"] == "active"
    assert enqueued == [
        (
            "platform.company_status_changed",
            {"countdown": 0, "company_id": str(shop.company_id), "status": "active"},
        )
    ]

    second = _pay(client, admin_headers, shop.company_id, f"paiement-{uuid4().hex}")
    later_end = datetime.fromisoformat(second.json()["current_period_end"])
    assert timedelta(days=55) < later_end - datetime.now(UTC) < timedelta(days=63)

    tables = [
        (row.entity_table, row.action)
        for row in _audit_rows(platform_session_factory, shop.company_id)
    ]
    assert tables.count(("subscription_payments", "insert")) == 2


def test_the_same_key_never_pays_twice(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany
) -> None:
    key = f"paiement-{uuid4().hex}"
    first = _pay(client, admin_headers, shop.company_id, key)
    again = _pay(client, admin_headers, shop.company_id, key)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.headers["Idempotent-Replay"] == "true"
    assert again.json()["payments_total"] == 1
    assert again.json()["current_period_end"] == first.json()["current_period_end"]

    other = _create_demo_company(f"abonne-{uuid4().hex[:8]}")
    reused = _pay(client, admin_headers, other.company_id, key)
    assert reused.status_code == 422
    assert reused.json()["error"]["code"] == "idempotency_key_reused"


@pytest.mark.parametrize(
    ("headers", "body", "code"),
    [
        ({}, {}, "idempotency_key_required"),
        ({"Idempotency-Key": "court"}, {}, "idempotency_key_malformed"),
        ({"Idempotency-Key": "cle-assez-longue"}, {"amount_fcfa": 4900.5}, "validation_failed"),
        ({"Idempotency-Key": "cle-assez-longue"}, {"amount_fcfa": "0"}, "validation_failed"),
        ({"Idempotency-Key": "cle-assez-longue"}, {"method": "cheque"}, "validation_failed"),
        (
            {"Idempotency-Key": "cle-assez-longue"},
            {"paid_at": (datetime.now(UTC) + timedelta(days=2)).isoformat()},
            "validation_failed",
        ),
    ],
)
def test_a_payment_is_refused_before_anything_is_written(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    headers: dict[str, str],
    body: dict[str, Any],
    code: str,
) -> None:
    payload = {
        "amount_fcfa": "4900",
        "paid_at": datetime.now(UTC).isoformat(),
        "method": "wave",
        **body,
    }
    response = client.post(
        _url(shop.company_id, "payments"), headers={**admin_headers, **headers}, json=payload
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_a_refused_commit_records_nothing(
    administrator: PlatformAccount,
    shop: DemoCompany,
    owner_engine: Engine,
    platform_session_factory: sessionmaker[Any],
    enqueued: list[tuple[str, dict[str, Any]]],
    platform_bound_to_test_database: None,
) -> None:
    with TestClient(app, base_url=TEST_BASE_URL, raise_server_exceptions=False) as raw:
        headers = auth_headers(platform_login(raw, administrator))
        enqueued.clear()  # l'alerte « nouvel appareil » de la connexion (ADR 0105)
        with failing_platform_commit(owner_engine):
            paid = _pay(raw, headers, shop.company_id, f"paiement-{uuid4().hex}")
            changed = raw.patch(
                _url(shop.company_id),
                headers=headers,
                json={"plan_code": "business", "status": "suspended", "reason": "refusé"},
            )
            rights = raw.put(
                _url(shop.company_id, "subscription/acquired-rights"),
                headers=headers,
                json={"extra_features": ["imports"], "max_users_override": 9, "reason": "refusé"},
            )
            extended = raw.post(
                _url(shop.company_id, "subscription/extend"),
                headers=headers,
                json={"days": 7, "reason": "refusé"},
            )
        assert paid.status_code >= 500 and changed.status_code >= 500
        assert rights.status_code >= 500 and extended.status_code >= 500
    row = subscription_row(platform_session_factory, shop.company_id)
    assert (row.plan_code, row.status, row.current_period_end) == ("starter", "trial", None)
    assert abs(row.trial_ends_at - row.started_at - timedelta(days=30)) < timedelta(minutes=1)
    assert (row.extra_features, row.max_users_override) == ([], None)
    assert enqueued == []


# -------------------------------------------------------------- cloisonnement


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/platform/plans"),
        ("GET", "/api/v1/platform/companies/{id}/subscription"),
        ("PATCH", "/api/v1/platform/companies/{id}/subscription"),
        ("POST", "/api/v1/platform/companies/{id}/payments"),
        ("PUT", "/api/v1/platform/companies/{id}/subscription/acquired-rights"),
    ],
)
def test_a_merchant_token_opens_none_of_them(
    client: TestClient, shop: DemoCompany, method: str, path: str
) -> None:
    token = login_token(client, shop)
    response = client.request(
        method,
        path.format(id=shop.company_id),
        headers={**auth_headers(token), "Idempotency-Key": uuid4().hex},
        json={"status": "active", "reason": "tentative"} if method in ("PATCH", "PUT") else None,
    )
    assert response.status_code == 401


# ------------------------------------------------- offres Pro et Business (ADR 0132)


def test_a_year_paid_moves_the_end_twelve_months(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany
) -> None:
    response = _pay(
        client,
        admin_headers,
        shop.company_id,
        f"an-{uuid4().hex}",
        amount_fcfa="52920",
        period_months=12,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    end = datetime.fromisoformat(body["current_period_end"])
    assert timedelta(days=364) <= end - datetime.now(UTC) <= timedelta(days=366)
    assert body["payments"][0]["period_months"] == 12

    # Un mois ensuite : depuis la fin en cours, la plus lointaine.
    month = _pay(client, admin_headers, shop.company_id, f"mois-{uuid4().hex}")
    later = datetime.fromisoformat(month.json()["current_period_end"])
    assert timedelta(days=28) <= later - end <= timedelta(days=31)


@pytest.mark.parametrize(
    ("amount", "months", "expected"),
    [("4900", 12, "52920.00"), ("52920", 1, "4900.00"), ("4800", 1, "4900.00")],
)
def test_a_wrong_amount_is_refused_with_the_expected_one(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
    amount: str,
    months: int,
    expected: str,
) -> None:
    response = _pay(
        client,
        admin_headers,
        shop.company_id,
        uuid4().hex,
        amount_fcfa=amount,
        period_months=months,
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "payment_amount_mismatch"
    assert error["details"] == {"expected_amount_fcfa": expected, "period_months": months}
    row = subscription_row(platform_session_factory, shop.company_id)
    assert (row.status, row.current_period_end) == ("trial", None)


def test_only_one_six_or_twelve_months(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany
) -> None:
    response = _pay(client, admin_headers, shop.company_id, uuid4().hex, period_months=3)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_premium_is_set_by_the_administrator_and_paid_on_quote(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
) -> None:
    moved = client.patch(
        _url(shop.company_id),
        headers=admin_headers,
        json={"plan_code": "premium", "reason": "Devis signé"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["plan"]["code"] == "premium"
    paid = _pay(
        client,
        admin_headers,
        shop.company_id,
        uuid4().hex,
        amount_fcfa="180000",
        period_months=12,
    )
    assert paid.status_code == 201, paid.text


def test_acquired_rights_are_set_with_a_reason_and_audited(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    url = _url(shop.company_id, "subscription/acquired-rights")
    response = client.put(
        url,
        headers=admin_headers,
        json={"extra_features": ["imports"], "max_users_override": 5, "reason": "Client fidèle"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["extra_features"], body["max_users_override"], body["max_users"]) == (
        ["imports"],
        5,
        5,
    )
    [row] = _audit_rows(platform_session_factory, shop.company_id)
    assert row.diff == {
        "before": {"extra_features": [], "max_users_override": None},
        "after": {"extra_features": ["imports"], "max_users_override": 5},
        "reason": "Client fidèle",
    }
    again = client.put(
        url,
        headers=admin_headers,
        json={"extra_features": ["imports"], "max_users_override": 5, "reason": "Rien"},
    )
    assert again.status_code == 200
    assert len(_audit_rows(platform_session_factory, shop.company_id)) == 1

    manager = auth_headers(login_token(client, shop))
    for n in range(3):
        created = client.post(
            "/api/v1/users",
            headers=manager,
            json={"full_name": f"Vendeur {n}", "email": f"a{n}-{uuid4().hex[:6]}@test.example"},
        )
        assert created.status_code == 201, created.text
    # 4 comptes actifs : retirer le plafond acquis (Pro = 3) est refusé.
    removed = client.put(
        url,
        headers=admin_headers,
        json={"extra_features": [], "max_users_override": None, "reason": "Retrait"},
    )
    assert removed.status_code == 409
    assert removed.json()["error"]["details"]["to_deactivate"] == 1


@pytest.mark.parametrize(
    "body",
    [
        {"extra_features": ["sales"], "reason": "commun à toutes les offres"},
        {"extra_features": ["inconnu"], "reason": "absent du catalogue"},
        {"extra_features": [], "max_users_override": 0, "reason": "zéro compte"},
        {"extra_features": []},
    ],
)
def test_impossible_acquired_rights_are_422(
    client: TestClient, admin_headers: dict[str, str], shop: DemoCompany, body: dict[str, Any]
) -> None:
    response = client.put(
        _url(shop.company_id, "subscription/acquired-rights"), headers=admin_headers, json=body
    )
    assert response.status_code == 422


def test_support_cannot_set_acquired_rights(client: TestClient, shop: DemoCompany) -> None:
    support = auth_headers(platform_login(client, create_platform_account("support")))
    response = client.put(
        _url(shop.company_id, "subscription/acquired-rights"),
        headers=support,
        json={"extra_features": ["imports"], "reason": "tentative"},
    )
    assert response.status_code == 403


def test_a_downgrade_counts_the_acquired_cap(
    client: TestClient,
    admin_headers: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    set_subscription(platform_session_factory, shop.company_id, plan="business")
    manager = auth_headers(login_token(client, shop))
    for n in range(4):
        client.post(
            "/api/v1/users",
            headers=manager,
            json={"full_name": f"V {n}", "email": f"d{n}-{uuid4().hex[:6]}@test.example"},
        )
    set_subscription(platform_session_factory, shop.company_id, max_users_override=5)
    moved = client.patch(
        _url(shop.company_id),
        headers=admin_headers,
        json={"plan_code": "starter", "reason": "Le plafond acquis suffit"},
    )
    assert moved.status_code == 200, moved.text
    assert (moved.json()["plan"]["code"], moved.json()["max_users"]) == ("starter", 5)
