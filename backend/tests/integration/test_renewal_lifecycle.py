"""Relances de fin d'essai et d'échéance, délai de grâce, suspension à J+3 (ADR 0133).

La tâche de nuit tourne jour par jour, horloge déplacée, de E-7 à E+4 : exactement la
veille, le jour J (abonnement `past_due`, accès inchangé), le dernier rappel à J+2 et la
suspension à J+3, une fois chacun, pour un essai comme pour une période payée.
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

from app.core import mailer
from app.core.tenancy import TenantContext, tenant_transaction
from app.main import app
from app.modules.platform import service as platform_service
from app.workers.tasks import platform as platform_tasks
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
)
from tests.integration.billing_harness import set_subscription, subscription_row
from tests.integration.platform_harness import create_platform_account, platform_login

pytestmark = pytest.mark.usefixtures("platform_bound_to_test_database")

#: Midi à Dakar (UTC+0) ; la tâche tourne à 06 h 30, le même jour calendaire. Toujours
#: dans le passé : avancer l'horloge de la tâche relancerait aussi les entreprises que la
#: suite partage (essai de 30 jours), reculer ne les touche pas.
END = (datetime.now(UTC) - timedelta(days=50)).replace(hour=12, minute=0, second=0, microsecond=0)


def night(offset: int) -> datetime:
    return (END + timedelta(days=offset)).replace(hour=6, minute=30)


@pytest.fixture
def shop() -> DemoCompany:
    return _create_demo_company(f"relance-{uuid4().hex[:8]}")


def _trial(factory: sessionmaker[Any], company_id: UUID, ends: datetime = END) -> None:
    set_subscription(factory, company_id, status="trial", trial_ends_at=ends)


def _paid(factory: sessionmaker[Any], company_id: UUID, ends: datetime = END) -> None:
    set_subscription(factory, company_id, status="active", current_period_end=ends)
    _set_access(factory, company_id, "active")


def _set_access(factory: sessionmaker[Any], company_id: UUID, status: str) -> None:
    with factory.begin() as session:
        session.execute(
            text("UPDATE companies SET status = CAST(:s AS company_status) WHERE id = :id"),
            {"s": status, "id": company_id},
        )


def _run(moment: datetime, company_id: UUID) -> list[str]:
    """Lance la tâche à `moment` ; les étapes vues pour cette entreprise seulement."""
    return [
        n.stage for n in platform_service.run_subscription_day(moment) if n.company_id == company_id
    ]


def _access(factory: sessionmaker[Any], company_id: UUID) -> str:
    with factory.begin() as session:
        return str(
            session.execute(
                text("SELECT status::text FROM companies WHERE id = :id"), {"id": company_id}
            ).scalar_one()
        )


def _walk(factory: sessionmaker[Any], company_id: UUID) -> list[tuple[int, str, str, str]]:
    """E-7 à E+4, deux passages par nuit : (jour, étape, abonnement, accès)."""
    seen: list[tuple[int, str, str, str]] = []
    for offset in range(-7, 5):
        for stage in _run(night(offset), company_id) + _run(night(offset), company_id):
            row = subscription_row(factory, company_id)
            seen.append((offset, stage, row.status, _access(factory, company_id)))
    return seen


def test_a_trial_day_by_day(platform_session_factory: sessionmaker[Any], shop: DemoCompany) -> None:
    _trial(platform_session_factory, shop.company_id)
    assert _walk(platform_session_factory, shop.company_id) == [
        (-1, "eve", "trial", "trial"),
        (0, "due", "past_due", "trial"),
        (2, "last", "past_due", "trial"),
        (3, "suspended", "suspended", "suspended"),
    ]
    row = subscription_row(platform_session_factory, shop.company_id)
    assert (row.reminder_stage, row.reminder_for_end) == ("suspended", END)
    with platform_session_factory.begin() as session:
        audits = session.execute(
            text(
                "SELECT entity_table, actor_id, diff ->> 'reason' AS reason "
                "FROM platform_audit_logs WHERE target_company_id = :id ORDER BY id"
            ),
            {"id": shop.company_id},
        ).all()
    assert [(a.entity_table, a.actor_id, a.reason) for a in audits] == [
        ("subscriptions", None, "fin de l'essai sans paiement"),
        ("companies", None, "fin de l'essai sans paiement"),
    ]


def test_a_paid_period_day_by_day(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    _paid(platform_session_factory, shop.company_id)
    assert _walk(platform_session_factory, shop.company_id) == [
        (-1, "eve", "active", "active"),
        (0, "due", "past_due", "active"),
        (2, "last", "past_due", "active"),
        (3, "suspended", "suspended", "suspended"),
    ]


def test_a_missed_night_sends_only_todays_step_and_never_suspends_early(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    _trial(platform_session_factory, shop.company_id)
    assert _run(night(1), shop.company_id) == ["due"]  # veille et jour J manqués
    assert _run(night(4), shop.company_id) == ["last"]  # J+2 et J+3 manqués
    assert _access(platform_session_factory, shop.company_id) == "trial"
    assert _run(night(5), shop.company_id) == ["suspended"]


def test_a_period_already_expired_at_deployment_is_warned_before_the_pause(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    _paid(platform_session_factory, shop.company_id, END - timedelta(days=60))
    assert _run(night(0), shop.company_id) == ["last"]
    assert _run(night(0) + timedelta(hours=3), shop.company_id) == []
    assert _run(night(1), shop.company_id) == ["suspended"]


def test_companies_already_advanced_or_suspended_at_deployment(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    # Déjà prévenue à J-7 et J-3 par l'ancien calendrier : la suite est la nouvelle.
    set_subscription(
        platform_session_factory,
        shop.company_id,
        status="trial",
        trial_ends_at=END,
        trial_warned_days=3,
    )
    assert _run(night(-3), shop.company_id) == []
    assert _run(night(-1), shop.company_id) == ["eve"]

    other = _create_demo_company(f"relance-{uuid4().hex[:8]}")
    set_subscription(platform_session_factory, other.company_id, status="suspended")
    _set_access(platform_session_factory, other.company_id, "suspended")
    for offset in range(-1, 5):
        assert _run(night(offset), other.company_id) == []
    assert _access(platform_session_factory, other.company_id) == "suspended"


def test_the_company_time_zone_decides_the_day(
    platform_session_factory: sessionmaker[Any], owner_engine: Engine, shop: DemoCompany
) -> None:
    # Échéance à 23 h 30 UTC : déjà le lendemain à Douala (UTC+1).
    ends = END.replace(hour=23, minute=30)
    _trial(platform_session_factory, shop.company_id, ends)
    with owner_engine.begin() as connection:  # `companies` est en RLS FORCE
        connection.execute(
            text("SELECT set_config('app.company_id', :id, true)"), {"id": str(shop.company_id)}
        )
        updated = connection.execute(
            text("UPDATE companies SET timezone = 'Africa/Douala' WHERE id = :id"),
            {"id": shop.company_id},
        )
        assert updated.rowcount == 1
    assert _run(night(-1), shop.company_id) == []  # J-2 à Douala
    assert _run(night(0), shop.company_id) == ["eve"]


@pytest.mark.parametrize("license", [True, False])
def test_a_licence_or_premium_without_end_receives_nothing(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany, license: bool
) -> None:
    set_subscription(
        platform_session_factory,
        shop.company_id,
        plan="premium",
        status="active",
        current_period_end=None,
        trial_ends_at=END - timedelta(days=40),
        is_license=license,
    )
    _set_access(platform_session_factory, shop.company_id, "active")
    for offset in (-1, 0, 2, 3, 40):
        assert _run(night(offset), shop.company_id) == []
    assert _access(platform_session_factory, shop.company_id) == "active"


# ----------------------------------------------- paiement, prolongation (administration)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL) as test_client:
        yield test_client


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    return auth_headers(platform_login(client, create_platform_account("administrator")))


@pytest.fixture(autouse=True)
def _no_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import queue

    monkeypatch.setattr(queue, "enqueue", lambda *args, **kwargs: None)


def _pay(client: TestClient, headers: dict[str, str], company_id: UUID, paid_at: datetime) -> Any:
    response = client.post(
        f"/api/v1/platform/companies/{company_id}/payments",
        headers={**headers, "Idempotency-Key": f"paiement-{uuid4().hex}"},
        json={"amount_fcfa": "4900", "paid_at": paid_at.isoformat(), "method": "wave"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_renewal_paid_during_grace_starts_from_the_old_end(
    client: TestClient,
    admin: dict[str, str],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    ends = datetime.now(UTC) - timedelta(days=1)
    _paid(platform_session_factory, shop.company_id, ends)
    set_subscription(platform_session_factory, shop.company_id, status="past_due")
    body = _pay(client, admin, shop.company_id, datetime.now(UTC))
    assert body["status"] == "active"
    new_end = datetime.fromisoformat(body["current_period_end"])
    assert ends + timedelta(days=27) < new_end < ends + timedelta(days=32)
    # Les rappels s'arrêtent : la nouvelle échéance est loin.
    assert _run(datetime.now(UTC) + timedelta(days=2), shop.company_id) == []


def test_a_trial_paid_at_j_plus_1_is_active_from_the_payment_day(
    client: TestClient,
    admin: dict[str, str],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    ends = datetime.now(UTC) - timedelta(days=1)
    _trial(platform_session_factory, shop.company_id, ends)
    assert _run(datetime.now(UTC), shop.company_id) == ["due"]
    body = _pay(client, admin, shop.company_id, datetime.now(UTC))
    assert body["status"] == "active"
    new_end = datetime.fromisoformat(body["current_period_end"])
    assert timedelta(days=27) < new_end - datetime.now(UTC) < timedelta(days=32)
    assert _access(platform_session_factory, shop.company_id) == "active"
    for offset in range(1, 6):
        assert _run(datetime.now(UTC) + timedelta(days=offset), shop.company_id) == []


def test_a_payment_after_the_pause_reactivates_from_the_payment_day(
    client: TestClient,
    admin: dict[str, str],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    ends = datetime.now(UTC) - timedelta(days=10)
    _paid(platform_session_factory, shop.company_id, ends)
    set_subscription(platform_session_factory, shop.company_id, status="suspended")
    _set_access(platform_session_factory, shop.company_id, "suspended")
    body = _pay(client, admin, shop.company_id, datetime.now(UTC))
    new_end = datetime.fromisoformat(body["current_period_end"])
    assert timedelta(days=27) < new_end - datetime.now(UTC) < timedelta(days=32)
    assert _access(platform_session_factory, shop.company_id) == "active"


def _extend(
    client: TestClient, headers: dict[str, str], company_id: UUID, days: int, reason: str
) -> Any:
    return client.post(
        f"/api/v1/platform/companies/{company_id}/subscription/extend",
        headers=headers,
        json={"days": days, "reason": reason},
    )


def test_extend_adds_days_to_the_end_and_restarts_the_calendar(
    client: TestClient,
    admin: dict[str, str],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    ends = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)
    _trial(platform_session_factory, shop.company_id, ends)
    assert _run(datetime.now(UTC), shop.company_id) == ["eve"]
    response = _extend(client, admin, shop.company_id, 7, "Le gérant revient de voyage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert datetime.fromisoformat(body["trial_ends_at"]) == ends + timedelta(days=7)
    row = subscription_row(platform_session_factory, shop.company_id)
    assert (row.status, row.reminder_stage) == ("trial", None)
    assert _run(ends + timedelta(days=6), shop.company_id) == ["eve"]

    with platform_session_factory.begin() as session:
        [audit] = session.execute(
            text(
                "SELECT actor_id, diff FROM platform_audit_logs WHERE target_company_id = :id "
                "AND entity_table = 'subscriptions' AND diff ->> 'reason' = :r"
            ),
            {"id": shop.company_id, "r": "Le gérant revient de voyage"},
        ).all()
    assert audit.actor_id is not None
    assert audit.diff["days"] == 7


def test_extend_a_suspended_shop_counts_from_today_and_reopens(
    client: TestClient,
    admin: dict[str, str],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    ends = datetime.now(UTC) - timedelta(days=5)
    _paid(platform_session_factory, shop.company_id, ends)
    set_subscription(
        platform_session_factory,
        shop.company_id,
        status="suspended",
        reminder_stage="suspended",
        reminder_for_end=ends,
        reminder_at=ends + timedelta(days=3),
    )
    _set_access(platform_session_factory, shop.company_id, "suspended")
    body = _extend(client, admin, shop.company_id, 10, "Paiement promis lundi").json()
    new_end = datetime.fromisoformat(body["current_period_end"])
    assert timedelta(days=9, hours=23) < new_end - datetime.now(UTC) <= timedelta(days=10)
    assert body["status"] == "active"
    assert _access(platform_session_factory, shop.company_id) == "active"


@pytest.mark.parametrize(
    ("days", "reason"), [(0, "Raison valable"), (91, "Raison valable"), (7, "  ")]
)
def test_extend_is_refused_without_a_reason_or_out_of_bounds(
    client: TestClient, admin: dict[str, str], shop: DemoCompany, days: int, reason: str
) -> None:
    response = _extend(client, admin, shop.company_id, days, reason)
    assert response.status_code == 422


def test_support_cannot_extend(client: TestClient, shop: DemoCompany) -> None:
    support = auth_headers(platform_login(client, create_platform_account("support")))
    assert _extend(client, support, shop.company_id, 7, "Raison valable").status_code == 403


def test_the_reminders_list_shows_the_step_and_the_managers_phone(
    client: TestClient,
    admin: dict[str, str],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    _trial(platform_session_factory, shop.company_id, datetime.now(UTC) + timedelta(days=1))
    far = _create_demo_company(f"relance-{uuid4().hex[:8]}")
    _trial(platform_session_factory, far.company_id, datetime.now(UTC) + timedelta(days=9))
    response = client.get("/api/v1/platform/reminders", headers=admin)
    assert response.status_code == 200
    items = {item["company_id"]: item for item in response.json()["items"]}
    assert str(far.company_id) not in items
    mine = items[str(shop.company_id)]
    assert (mine["stage"], mine["kind"], mine["status"]) == ("eve", "trial", "trial")
    assert "se termine demain" in mine["message"]
    assert mine["contacts"][0]["full_name"]
    attention = client.get("/api/v1/platform/attention", headers=admin).json()
    assert attention["reminders"] >= 1


# ---------------------------------------------------------------- le worker


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    mails: list[dict[str, Any]] = []

    def _send(**message: Any) -> bool:
        mails.append(message)
        return True

    monkeypatch.setattr(mailer, "send_email", _send)
    return mails


def _bells(session_factory: sessionmaker[Any], company_id: UUID) -> list[Any]:
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        return list(
            session.execute(
                text(
                    "SELECT title, data -> 'push' ->> 'url' AS url FROM notifications "
                    "WHERE type = 'trial_ending' ORDER BY created_at"
                )
            ).all()
        )


def _notice(company_id: UUID, stage: str, kind: str = "trial") -> dict[str, Any]:
    return {
        "company_id": str(company_id),
        "stage": stage,
        "kind": kind,
        "ends_at": END.isoformat(),
        "plan_name": "Pro",
        "pause_on": (END + timedelta(days=3)).date().isoformat(),
        "today": (END + timedelta(days={"eve": -1, "due": 0, "last": 2}.get(stage, 3)))
        .date()
        .isoformat(),
    }


@pytest.mark.usefixtures("workers_bound_to_test_database")
def test_each_step_rings_and_mails_once(
    session_factory: sessionmaker[Any], shop: DemoCompany, sent: list[dict[str, Any]]
) -> None:
    for stage in ("eve", "due", "last"):
        assert platform_tasks.renewal_notice(**_notice(shop.company_id, stage)) is True
        assert platform_tasks.renewal_notice(**_notice(shop.company_id, stage)) is False
    bells = _bells(session_factory, shop.company_id)
    assert [bell.title for bell in bells] == [
        "Votre essai se termine demain",
        "Votre essai se termine aujourd'hui",
        "Dernier rappel : pause demain",
    ]
    assert {bell.url for bell in bells} == {"/settings/subscription"}
    assert [mail["to"] for mail in sent] == [[shop.email]] * 3
    assert "Votre essai gratuit de CoGes Pro se termine demain" in sent[0]["body"]
    assert "reste ouverte encore 3 jours" in sent[1]["body"]
    assert "sera mise en pause demain" in sent[2]["body"]


@pytest.mark.usefixtures("workers_bound_to_test_database")
def test_a_paid_period_speaks_of_the_subscription(
    session_factory: sessionmaker[Any], shop: DemoCompany, sent: list[dict[str, Any]]
) -> None:
    platform_tasks.renewal_notice(**_notice(shop.company_id, "eve", "paid"))
    assert [bell.title for bell in _bells(session_factory, shop.company_id)] == [
        "Votre abonnement se termine demain"
    ]
    assert "Votre abonnement CoGes Pro se termine demain" in sent[0]["body"]


@pytest.mark.usefixtures("workers_bound_to_test_database")
def test_the_pause_is_mailed_without_a_bell(
    session_factory: sessionmaker[Any], shop: DemoCompany, sent: list[dict[str, Any]]
) -> None:
    platform_tasks.renewal_notice(**_notice(shop.company_id, "suspended"))
    assert _bells(session_factory, shop.company_id) == []
    [mail] = sent
    assert mail["subject"] == "Votre boutique est en pause"
    assert "Vos données sont gardées" in mail["body"]


@pytest.mark.usefixtures("workers_bound_to_test_database")
def test_a_manager_without_email_gets_the_bell_without_error(
    session_factory: sessionmaker[Any],
    owner_engine: Engine,
    shop: DemoCompany,
    sent: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform_tasks, "manager_emails", lambda company_id: ("Boutique", []))
    assert platform_tasks.renewal_notice(**_notice(shop.company_id, "due")) is True
    assert len(_bells(session_factory, shop.company_id)) == 1
    assert [mail["to"] for mail in sent] in ([], [[]])


def test_the_daily_task_queues_one_notice_per_step_after_commit(
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued: list[dict[str, Any]] = []
    summaries: list[Any] = []
    monkeypatch.setattr(
        platform_tasks.renewal_notice, "delay", lambda **kwargs: queued.append(kwargs)
    )
    monkeypatch.setattr(platform_tasks.trial_summary, "delay", summaries.append)
    _trial(platform_session_factory, shop.company_id)
    platform_tasks.subscriptions_daily(night(-1).isoformat())
    mine = [kwargs for kwargs in queued if kwargs["company_id"] == str(shop.company_id)]
    assert mine == [_notice(shop.company_id, "eve")]
    [summary] = summaries
    assert any(item["stage"] == "eve" for item in summary)


# ------------------------------------------------------------- le bandeau (/auth/me)


@pytest.mark.parametrize(
    ("offset", "renewal"),
    [
        (2, None),
        (1, {"stage": "eve", "kind": "trial", "days_left": 4}),
        (0, {"stage": "due", "kind": "trial", "days_left": 3}),
        (-2, {"stage": "last", "kind": "trial", "days_left": 1}),
    ],
)
def test_me_tells_the_banner_the_step_of_the_day(
    api_client: TestClient,
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
    offset: int,
    renewal: dict[str, Any] | None,
) -> None:
    ends = datetime.now(UTC) + timedelta(days=offset)
    _trial(platform_session_factory, shop.company_id, ends)
    me = api_client.get("/api/v1/auth/me", headers=auth_headers(login_token(api_client, shop)))
    found = me.json()["plan"]["renewal"]
    if renewal is None:
        assert found is None
    else:
        assert {key: found[key] for key in renewal} == renewal
        assert datetime.fromisoformat(found["ends_at"]) == ends


def test_me_has_no_banner_for_a_licence(
    api_client: TestClient, platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    set_subscription(
        platform_session_factory,
        shop.company_id,
        status="active",
        is_license=True,
        current_period_end=datetime.now(UTC),
    )
    me = api_client.get("/api/v1/auth/me", headers=auth_headers(login_token(api_client, shop)))
    assert me.json()["plan"]["renewal"] is None
