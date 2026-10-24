"""Fin des essais, la tâche de nuit (ADR 0091).

J-8 : rien. J-7, J-3, J-1 : un avertissement chacun, jamais deux. J+0 exact : suspension,
une fois. La sous-tâche par entreprise pose la cloche du gérant une seule fois, et ne
renvoie pas l'e-mail quand elle est rejouée.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core import mailer
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.platform import service as platform_service
from app.workers.tasks import platform as platform_tasks
from tests.conftest import DemoCompany, _create_demo_company
from tests.integration.billing_harness import subscription_row, trial_ends_in

pytestmark = pytest.mark.usefixtures("platform_bound_to_test_database")

NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
def shop() -> DemoCompany:
    return _create_demo_company(f"essai-{uuid4().hex[:8]}")


def _day(now: datetime, company_id: UUID) -> list[int]:
    """Lance la tâche à `now` et rend les paliers vus pour cette entreprise seulement."""
    return [
        n.days for n in platform_service.run_subscription_day(now) if n.company_id == company_id
    ]


def _company_status(platform_session_factory: sessionmaker[Any], company_id: UUID) -> str:
    with platform_session_factory.begin() as session:
        return str(
            session.execute(
                text("SELECT status::text FROM companies WHERE id = :id"), {"id": company_id}
            ).scalar_one()
        )


def test_eight_days_before_nothing_happens(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    trial_ends_in(platform_session_factory, shop.company_id, NOW + timedelta(days=8))
    assert _day(NOW, shop.company_id) == []
    assert subscription_row(platform_session_factory, shop.company_id).trial_warned_days is None


def test_each_warning_is_given_once_seven_three_then_one(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    ends = NOW + timedelta(days=7)
    trial_ends_in(platform_session_factory, shop.company_id, ends)
    assert _day(NOW, shop.company_id) == [7]
    assert _day(NOW, shop.company_id) == []  # relancée : rien de plus
    assert _day(ends - timedelta(days=5), shop.company_id) == []  # J-5 : déjà prévenue
    assert _day(ends - timedelta(days=3), shop.company_id) == [3]
    assert _day(ends - timedelta(days=2), shop.company_id) == []
    assert _day(ends - timedelta(hours=20), shop.company_id) == [1]
    assert _day(ends - timedelta(hours=1), shop.company_id) == []
    row = subscription_row(platform_session_factory, shop.company_id)
    assert (row.status, row.trial_warned_days) == ("trial", 1)


def test_a_missed_night_gives_the_nearest_warning_only(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    trial_ends_in(platform_session_factory, shop.company_id, NOW + timedelta(days=2))
    assert _day(NOW, shop.company_id) == [3]


def test_the_day_before_does_not_suspend_the_exact_end_does_once(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    ends = NOW + timedelta(days=1)
    trial_ends_in(platform_session_factory, shop.company_id, ends)
    assert _day(NOW, shop.company_id) == [1]
    assert _company_status(platform_session_factory, shop.company_id) == "trial"

    assert _day(ends, shop.company_id) == [0]  # J+0 exact
    assert subscription_row(platform_session_factory, shop.company_id).status == "suspended"
    assert _company_status(platform_session_factory, shop.company_id) == "suspended"
    assert _day(ends + timedelta(hours=1), shop.company_id) == []  # relancée : une fois

    with platform_session_factory.begin() as session:
        audits = session.execute(
            text(
                "SELECT entity_table, actor_id FROM platform_audit_logs "
                "WHERE target_company_id = :id ORDER BY id"
            ),
            {"id": shop.company_id},
        ).all()
    assert [(row.entity_table, row.actor_id) for row in audits] == [
        ("subscriptions", None),
        ("companies", None),
    ]


def test_a_paid_subscription_is_never_suspended(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    trial_ends_in(platform_session_factory, shop.company_id, NOW - timedelta(days=1))
    with platform_session_factory.begin() as session:
        session.execute(
            text("UPDATE subscriptions SET status = 'active' WHERE company_id = :id"),
            {"id": shop.company_id},
        )
    assert _day(NOW, shop.company_id) == []
    assert _company_status(platform_session_factory, shop.company_id) == "trial"


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
                text("SELECT title FROM notifications WHERE type = 'trial_ending'")
            ).scalars()
        )


@pytest.mark.usefixtures("workers_bound_to_test_database")
def test_the_notice_rings_the_bell_once_and_mails_once(
    session_factory: sessionmaker[Any], shop: DemoCompany, sent: list[dict[str, Any]]
) -> None:
    ends = (NOW + timedelta(days=3)).isoformat()
    assert platform_tasks.trial_notice(str(shop.company_id), 3, ends) is True
    assert platform_tasks.trial_notice(str(shop.company_id), 3, ends) is False
    assert _bells(session_factory, shop.company_id) == ["Votre essai se termine dans 3 jours"]
    [mail] = sent
    assert mail["to"] == [shop.email]
    assert mail["subject"] == "Votre essai de CoGes se termine dans 3 jours"
    assert "Merci de faire confiance à CoGes" in mail["body"]


@pytest.mark.usefixtures("workers_bound_to_test_database")
def test_the_end_of_trial_mails_without_a_bell(
    session_factory: sessionmaker[Any], shop: DemoCompany, sent: list[dict[str, Any]]
) -> None:
    platform_tasks.trial_notice(str(shop.company_id), 0, NOW.isoformat())
    assert _bells(session_factory, shop.company_id) == []
    assert [mail["subject"] for mail in sent] == ["Votre essai de CoGes est terminé"]


def test_the_daily_task_queues_one_notice_per_company_after_commit(
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued: list[tuple[Any, ...]] = []
    monkeypatch.setattr(platform_tasks.trial_notice, "delay", lambda *args: queued.append(args))
    monkeypatch.setattr(platform_tasks.trial_summary, "delay", lambda *args: None)
    ends = NOW + timedelta(days=7)
    trial_ends_in(platform_session_factory, shop.company_id, ends)
    platform_tasks.subscriptions_daily(NOW.isoformat())
    mine = [args for args in queued if args[0] == str(shop.company_id)]
    assert mine == [(str(shop.company_id), 7, ends.isoformat())]
