"""Statistiques de la plateforme (lot admin 5 ; ADR 0093).

Trois lectures, administrateur et support : les entreprises par statut et par offre (les
essais à part), le revenu **réellement déclaré** sur une période, les nouvelles
entreprises sur douze mois. La base de test est partagée : chaque test mesure un écart
avant / après, jamais un chiffre absolu.

Le revenu ne bouge que quand un paiement est enregistré — ni quand une offre change, ni
quand un essai commence, ni quand une entreprise est suspendue. Après chaque geste,
l'invariant tient : statuts = total = répartition par offre = décompte de la base.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
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
from tests.helpers.platform_invariants import database_violations, overview_violations
from tests.integration.platform_harness import (
    PlatformAccount,
    create_platform_account,
    platform_login,
)

OVERVIEW = "/api/v1/platform/stats/overview"
REVENUE = "/api/v1/platform/stats/revenue"
SIGNUPS = "/api/v1/platform/stats/signups"


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


@pytest.fixture(autouse=True)
def quiet_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les e-mails de suspension et de paiement ne partent pas d'ici."""
    monkeypatch.setattr(queue, "enqueue", lambda *_args, **_kwargs: True)


def _new_shop() -> DemoCompany:
    return _create_demo_company(f"stats-{uuid4().hex[:8]}")


def _get(client: TestClient, headers: dict[str, str], url: str, **params: str) -> Any:
    response = client.get(url, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _revenue(client: TestClient, headers: dict[str, str], **params: str) -> tuple[Decimal, int]:
    body = _get(client, headers, REVENUE, **params)
    return Decimal(body["total_fcfa"]), int(body["payment_count"])


def _pay(
    client: TestClient,
    headers: dict[str, str],
    company_id: UUID,
    amount: str,
    paid_at: datetime | None = None,
) -> None:
    response = client.post(
        f"/api/v1/platform/companies/{company_id}/payments",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={
            "amount_fcfa": amount,
            "paid_at": (paid_at or datetime.now(UTC)).isoformat(),
            "method": "wave",
        },
    )
    assert response.status_code == 201, response.text


def _consistent(client: TestClient, headers: dict[str, str], owner_engine: Engine) -> Any:
    overview = _get(client, headers, OVERVIEW)
    assert overview_violations(overview) == []
    assert database_violations(owner_engine, overview) == []
    return overview


def _plan(overview: Any, code: str) -> Any:
    return next(plan for plan in overview["plans"] if plan["code"] == code)


def _as_owner_in(owner_engine: Engine, company_id: UUID, statement: str, **params: Any) -> None:
    """`companies` est en RLS FORCE : le propriétaire écrit sous le contexte de l'entreprise."""
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :id, true)"), {"id": str(company_id)}
        )
        assert connection.execute(text(statement), {"id": company_id, **params}).rowcount == 1


# ------------------------------------------------------------------ vue d'ensemble


def test_the_overview_counts_statuses_offers_and_active_accounts(
    client: TestClient, admin_headers: dict[str, str], owner_engine: Engine
) -> None:
    before = _consistent(client, admin_headers, owner_engine)
    assert set(before) == {
        "computed_at",
        "companies",
        "active_users",
        "plans",
        "without_subscription",
    }
    assert set(before["companies"]) == {"trial", "active", "suspended", "total"}
    assert {plan["code"] for plan in before["plans"]} >= {"starter", "business", "premium"}
    assert set(before["plans"][0]) == {"code", "name", "trial", "paying", "suspended", "total"}

    _new_shop()
    after = _consistent(client, admin_headers, owner_engine)
    assert after["companies"]["trial"] == before["companies"]["trial"] + 1
    assert after["companies"]["total"] == before["companies"]["total"] + 1
    # L'essai est sur Premium, mais compté **à part** des entreprises payantes.
    assert _plan(after, "premium")["trial"] == _plan(before, "premium")["trial"] + 1
    assert _plan(after, "premium")["paying"] == _plan(before, "premium")["paying"]
    # Le gérant de la boutique de démonstration.
    assert after["active_users"] == before["active_users"] + 1


def test_the_invariant_holds_after_every_step(
    client: TestClient, admin_headers: dict[str, str], owner_engine: Engine
) -> None:
    before = _consistent(client, admin_headers, owner_engine)
    shop = _new_shop()
    _consistent(client, admin_headers, owner_engine)

    # Payée : l'entreprise passe dans les payantes de son offre.
    _pay(client, admin_headers, shop.company_id, "14900")
    paid = _consistent(client, admin_headers, owner_engine)
    assert paid["companies"]["active"] == before["companies"]["active"] + 1
    assert _plan(paid, "premium")["paying"] == _plan(before, "premium")["paying"] + 1

    # Change d'offre : elle quitte Premium pour Starter.
    changed = client.patch(
        f"/api/v1/platform/companies/{shop.company_id}/subscription",
        headers=admin_headers,
        json={"plan_code": "starter", "reason": "Le gérant préfère Starter"},
    )
    assert changed.status_code == 200, changed.text
    moved = _consistent(client, admin_headers, owner_engine)
    assert _plan(moved, "starter")["paying"] == _plan(before, "starter")["paying"] + 1
    assert _plan(moved, "premium")["paying"] == _plan(before, "premium")["paying"]

    # Suspendue (accès coupé par l'équipe, lot 1).
    suspended = client.patch(
        f"/api/v1/platform/companies/{shop.company_id}/status",
        headers=admin_headers,
        json={"status": "suspended", "reason": "Abus signalé"},
    )
    assert suspended.status_code == 200, suspended.text
    cut = _consistent(client, admin_headers, owner_engine)
    assert cut["companies"]["suspended"] == before["companies"]["suspended"] + 1

    # Supprimée : elle sort de tous les comptes, comme de la liste des entreprises.
    _as_owner_in(
        owner_engine, shop.company_id, "UPDATE companies SET deleted_at = now() WHERE id = :id"
    )
    gone = _consistent(client, admin_headers, owner_engine)
    assert gone["companies"] == before["companies"]
    assert gone["plans"] == before["plans"]
    assert gone["active_users"] == before["active_users"]


# ----------------------------------------------------------------------- revenu


def test_revenue_moves_only_when_a_payment_is_recorded(
    client: TestClient, admin_headers: dict[str, str], owner_engine: Engine
) -> None:
    total, count = _revenue(client, admin_headers, period="current_month")

    # Un essai qui commence : rien.
    shop = _new_shop()
    assert _revenue(client, admin_headers, period="current_month") == (total, count)

    # Une offre qui change, puis un abonnement suspendu : rien.
    for payload in (
        {"plan_code": "business", "reason": "Passage à Business"},
        {"status": "suspended", "reason": "Impayé"},
    ):
        response = client.patch(
            f"/api/v1/platform/companies/{shop.company_id}/subscription",
            headers=admin_headers,
            json=payload,
        )
        assert response.status_code == 200, response.text
        assert _revenue(client, admin_headers, period="current_month") == (total, count)

    # Un paiement enregistré : exactement son montant, une fois.
    _pay(client, admin_headers, shop.company_id, "9900")
    assert _revenue(client, admin_headers, period="current_month") == (
        total + Decimal("9900"),
        count + 1,
    )


def test_a_period_counts_its_days_to_the_second(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """Dakar est à UTC toute l'année : 23 h 59 min 59 s compte, minuit le lendemain non."""
    shop = _new_shop()
    day = datetime.now(UTC).date() - timedelta(days=10)
    following = day + timedelta(days=1)
    on_day = {"period": "custom", "start": day.isoformat(), "end": day.isoformat()}
    on_next = {"period": "custom", "start": following.isoformat(), "end": following.isoformat()}
    day_before, next_before = (
        _revenue(client, admin_headers, **on_day),
        _revenue(client, admin_headers, **on_next),
    )

    _pay(
        client, admin_headers, shop.company_id, "4900", datetime.combine(day, time(23, 59, 59), UTC)
    )
    _pay(client, admin_headers, shop.company_id, "14900", datetime.combine(following, time(0), UTC))

    assert _revenue(client, admin_headers, **on_day) == (
        day_before[0] + Decimal("4900"),
        day_before[1] + 1,
    )
    assert _revenue(client, admin_headers, **on_next) == (
        next_before[0] + Decimal("14900"),
        next_before[1] + 1,
    )


def test_the_named_periods_say_which_days_they_cover(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    today = datetime.now(UTC).date()
    current = _get(client, admin_headers, REVENUE, period="current_month")
    assert set(current) == {
        "period",
        "start",
        "end",
        "timezone",
        "total_fcfa",
        "payment_count",
        "computed_at",
    }
    assert (current["start"], current["end"], current["timezone"]) == (
        today.replace(day=1).isoformat(),
        today.isoformat(),
        "Africa/Dakar",
    )
    previous = _get(client, admin_headers, REVENUE, period="previous_month")
    last_day = today.replace(day=1) - timedelta(days=1)
    assert (previous["start"], previous["end"]) == (
        last_day.replace(day=1).isoformat(),
        last_day.isoformat(),
    )


def test_a_payment_of_last_month_counts_last_month(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    shop = _new_shop()
    last_day = datetime.now(UTC).date().replace(day=1) - timedelta(days=1)
    previous = _revenue(client, admin_headers, period="previous_month")
    current = _revenue(client, admin_headers, period="current_month")
    _pay(client, admin_headers, shop.company_id, "4900", datetime.combine(last_day, time(12), UTC))
    assert _revenue(client, admin_headers, period="previous_month") == (
        previous[0] + Decimal("4900"),
        previous[1] + 1,
    )
    assert _revenue(client, admin_headers, period="current_month") == current


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"period": "custom"}, "period_dates_required"),
        ({"period": "custom", "start": "2026-03-10", "end": "2026-03-01"}, "period_inverted"),
        ({"period": "custom", "start": "2025-01-01", "end": "2026-01-02"}, "period_too_long"),
        ({"period": "custom", "start": "2026-01-01", "end": "2999-01-01"}, "period_in_future"),
    ],
)
def test_an_impossible_period_is_422(
    client: TestClient, admin_headers: dict[str, str], params: dict[str, str], code: str
) -> None:
    response = client.get(REVENUE, headers=admin_headers, params=params)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code


def test_a_year_exactly_is_accepted(client: TestClient, admin_headers: dict[str, str]) -> None:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=365)  # 366 jours, bornes comprises
    response = client.get(
        REVENUE,
        headers=admin_headers,
        params={"period": "custom", "start": start.isoformat(), "end": end.isoformat()},
    )
    assert response.status_code == 200, response.text


def test_an_unknown_period_is_422(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert client.get(REVENUE, headers=admin_headers, params={"period": "year"}).status_code == 422


# ---------------------------------------------------------- nouvelles entreprises


def _bucket(body: Any, day: date) -> int:
    [match] = [
        bucket["count"]
        for bucket in body["buckets"]
        if date.fromisoformat(bucket["start"]) <= day <= date.fromisoformat(bucket["end"])
    ]
    return int(match)


@pytest.mark.parametrize(("granularity", "size"), [("month", 12), ("week", 52)])
def test_signups_cover_twelve_months_without_gaps(
    client: TestClient, admin_headers: dict[str, str], granularity: str, size: int
) -> None:
    body = _get(client, admin_headers, SIGNUPS, granularity=granularity)
    assert set(body) == {"granularity", "timezone", "computed_at", "buckets", "total"}
    buckets = body["buckets"]
    assert len(buckets) == size
    for previous, following in zip(buckets, buckets[1:], strict=False):
        assert date.fromisoformat(previous["end"]) + timedelta(days=1) == date.fromisoformat(
            following["start"]
        )
    assert all(bucket["count"] >= 0 for bucket in buckets)
    assert body["total"] == sum(bucket["count"] for bucket in buckets)
    today = datetime.now(UTC).date()
    assert (
        date.fromisoformat(buckets[-1]["start"]) <= today <= date.fromisoformat(buckets[-1]["end"])
    )
    if granularity == "week":
        assert all(date.fromisoformat(b["start"]).weekday() == 0 for b in buckets)
    else:
        assert all(date.fromisoformat(b["start"]).day == 1 for b in buckets)


def test_a_new_company_lands_in_its_month_and_week_and_leaves_when_deleted(
    client: TestClient, admin_headers: dict[str, str], owner_engine: Engine
) -> None:
    today = datetime.now(UTC).date()
    months, weeks = (
        _get(client, admin_headers, SIGNUPS, granularity="month"),
        _get(client, admin_headers, SIGNUPS, granularity="week"),
    )
    shop = _new_shop()
    assert _bucket(_get(client, admin_headers, SIGNUPS, granularity="month"), today) == (
        _bucket(months, today) + 1
    )
    assert _bucket(_get(client, admin_headers, SIGNUPS, granularity="week"), today) == (
        _bucket(weeks, today) + 1
    )

    # Créée il y a cinq mois : comptée dans ce mois-là, plus dans le mois en cours.
    five_months_ago = (today.replace(day=1) - timedelta(days=140)).replace(day=15)
    _as_owner_in(
        owner_engine,
        shop.company_id,
        "UPDATE companies SET created_at = :at WHERE id = :id",
        at=datetime.combine(five_months_ago, time(9), UTC),
    )
    moved = _get(client, admin_headers, SIGNUPS, granularity="month")
    assert _bucket(moved, today) == _bucket(months, today)
    assert _bucket(moved, five_months_ago) == _bucket(months, five_months_ago) + 1

    _as_owner_in(
        owner_engine, shop.company_id, "UPDATE companies SET deleted_at = now() WHERE id = :id"
    )
    assert _get(client, admin_headers, SIGNUPS, granularity="month")["buckets"] == months["buckets"]


def test_an_unknown_granularity_is_422(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get(SIGNUPS, headers=admin_headers, params={"granularity": "day"})
    assert response.status_code == 422


# ------------------------------------------------------------------------- accès


@pytest.mark.parametrize("url", [OVERVIEW, f"{REVENUE}?period=current_month", SIGNUPS])
def test_support_reads_the_statistics(client: TestClient, url: str) -> None:
    support = auth_headers(platform_login(client, create_platform_account("support")))
    assert client.get(url, headers=support).status_code == 200


@pytest.mark.parametrize("url", [OVERVIEW, f"{REVENUE}?period=current_month", SIGNUPS])
def test_neither_a_merchant_nor_a_stranger_reads_them(client: TestClient, url: str) -> None:
    shop = _new_shop()
    assert client.get(url, headers=auth_headers(login_token(client, shop))).status_code == 401
    assert client.get(url).status_code == 401
