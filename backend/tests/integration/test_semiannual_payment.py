"""Payer 6 mois d'un coup, sans remise (prompt 44, ADR 0134).

La base d'abord : `subscription_payments.period_months` accepte 1, 6 et 12, et
`plans.semiannual_price_fcfa` vaut exactement 6 fois le prix du mois (Pro et Business),
`NULL` pour Premium. Puis l'API : montant exigé, période avancée de 6 mois calendaires par
la même fonction que 1 et 12 (fin de mois comprise), idempotence, départ de la période
(ADR 0133) et calendrier des relances qui repart de zéro pour la nouvelle fin.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.modules.platform import service as platform_service
from tests.conftest import (
    BACKEND_ROOT,
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
)
from tests.integration.billing_harness import set_subscription, subscription_row
from tests.integration.platform_harness import create_platform_account, platform_login

pytestmark = pytest.mark.usefixtures("platform_bound_to_test_database")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL) as test_client:
        yield test_client


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    return auth_headers(platform_login(client, create_platform_account("administrator")))


@pytest.fixture
def shop() -> DemoCompany:
    return _create_demo_company(f"six-mois-{uuid4().hex[:8]}")


@pytest.fixture(autouse=True)
def _no_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import queue

    monkeypatch.setattr(queue, "enqueue", lambda *args, **kwargs: None)


def _pay(
    client: TestClient,
    headers: dict[str, str],
    company_id: UUID,
    amount: str,
    *,
    key: str | None = None,
    months: int = 6,
) -> Any:
    return client.post(
        f"/api/v1/platform/companies/{company_id}/payments",
        headers={**headers, "Idempotency-Key": key or f"six-{uuid4().hex}"},
        json={
            "amount_fcfa": amount,
            "paid_at": datetime.now(UTC).isoformat(),
            "method": "wave",
            "period_months": months,
        },
    )


def _paid(factory: sessionmaker[Any], company_id: UUID, ends: datetime, status: str) -> None:
    set_subscription(factory, company_id, status=status, current_period_end=ends)
    with factory.begin() as session:
        session.execute(
            text("UPDATE companies SET status = CAST(:s AS company_status) WHERE id = :id"),
            {"s": "suspended" if status == "suspended" else "active", "id": company_id},
        )


def _access(factory: sessionmaker[Any], company_id: UUID) -> str:
    with factory.begin() as session:
        return str(
            session.execute(
                text("SELECT status::text FROM companies WHERE id = :id"), {"id": company_id}
            ).scalar_one()
        )


def _stages(moment: datetime, company_id: UUID) -> list[str]:
    return [
        n.stage for n in platform_service.run_subscription_day(moment) if n.company_id == company_id
    ]


# ------------------------------------------------------------------ la base


def test_the_semiannual_price_is_six_months_without_discount(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        rows = {
            row.code: row
            for row in connection.execute(
                text(
                    "SELECT code, price_fcfa, semiannual_price_fcfa FROM plans "
                    "WHERE code IN ('starter', 'business', 'premium')"
                )
            )
        }
    for code in ("starter", "business"):
        assert rows[code].semiannual_price_fcfa == rows[code].price_fcfa * 6, code
    assert rows["starter"].semiannual_price_fcfa == Decimal("29400")
    assert rows["business"].semiannual_price_fcfa == Decimal("59400")
    assert rows["premium"].semiannual_price_fcfa is None


def test_the_database_accepts_one_six_or_twelve_months_only(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        definition = connection.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'subscription_payments'::regclass AND contype = 'c' "
                "AND pg_get_constraintdef(oid) LIKE '%period_months%'"
            )
        ).scalar_one()
    for months in ("1", "6", "12"):
        assert months in definition
    assert "3" not in definition.replace("period_months", "")


def test_a_semiannual_price_needs_a_monthly_one(owner_engine: Engine) -> None:
    with pytest.raises(IntegrityError), owner_engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET semiannual_price_fcfa = 1000 WHERE code = 'premium'")
        )


# ------------------------------------------------------------------ l'API


def test_six_months_paid_moves_the_end_six_months(
    client: TestClient,
    admin: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    response = _pay(client, admin, shop.company_id, "29400")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "active"
    assert body["payments"][0]["period_months"] == 6
    assert Decimal(body["payments"][0]["amount_fcfa"]) == Decimal("29400")
    assert Decimal(body["plan"]["semiannual_price_fcfa"]) == Decimal("29400")
    end = datetime.fromisoformat(body["current_period_end"])
    assert timedelta(days=180) <= end - datetime.now(UTC) <= timedelta(days=185)
    assert _access(platform_session_factory, shop.company_id) == "active"


@pytest.mark.parametrize(
    ("plan", "amount", "expected"),
    [
        ("starter", "4900", "29400.00"),
        ("starter", "26460", "29400.00"),  # 6 mois à -10 % : il n'y a pas de remise
        ("business", "29400", "59400.00"),
    ],
)
def test_a_wrong_six_month_amount_is_refused_with_the_expected_one(
    client: TestClient,
    admin: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
    plan: str,
    amount: str,
    expected: str,
) -> None:
    set_subscription(platform_session_factory, shop.company_id, plan=plan)
    response = _pay(client, admin, shop.company_id, amount)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "payment_amount_mismatch"
    assert error["details"] == {"expected_amount_fcfa": expected, "period_months": 6}
    row = subscription_row(platform_session_factory, shop.company_id)
    assert (row.status, row.current_period_end) == ("trial", None)


def test_business_pays_59400_for_six_months(
    client: TestClient,
    admin: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    set_subscription(platform_session_factory, shop.company_id, plan="business")
    response = _pay(client, admin, shop.company_id, "59400")
    assert response.status_code == 201, response.text


def test_premium_pays_six_months_on_quote(
    client: TestClient,
    admin: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    set_subscription(platform_session_factory, shop.company_id, plan="premium")
    response = _pay(client, admin, shop.company_id, "95000")
    assert response.status_code == 201, response.text
    assert response.json()["payments"][0]["period_months"] == 6


@pytest.mark.parametrize(
    ("ends", "expected"),
    [
        # 31 août + 6 mois : dernier jour de février, bissextile ou non.
        (datetime(2027, 8, 31, 12, tzinfo=UTC), datetime(2028, 2, 29, 12, tzinfo=UTC)),
        (datetime(2028, 8, 31, 12, tzinfo=UTC), datetime(2029, 2, 28, 12, tzinfo=UTC)),
        (datetime(2027, 12, 31, 12, tzinfo=UTC), datetime(2028, 6, 30, 12, tzinfo=UTC)),
    ],
)
def test_six_months_from_a_month_end_land_on_the_last_day(
    client: TestClient,
    admin: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
    ends: datetime,
    expected: datetime,
) -> None:
    _paid(platform_session_factory, shop.company_id, ends, "active")
    response = _pay(client, admin, shop.company_id, "29400")
    assert response.status_code == 201, response.text
    assert datetime.fromisoformat(response.json()["current_period_end"]) == expected


def test_the_same_key_never_pays_six_months_twice(
    client: TestClient,
    admin: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    key = f"six-{uuid4().hex}"
    first = _pay(client, admin, shop.company_id, "29400", key=key)
    second = _pay(client, admin, shop.company_id, "29400", key=key)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["current_period_end"] == second.json()["current_period_end"]
    with platform_session_factory.begin() as session:
        count = session.execute(
            text(
                "SELECT count(*) FROM subscription_payments p JOIN subscriptions s "
                "ON s.id = p.subscription_id WHERE s.company_id = :id"
            ),
            {"id": shop.company_id},
        ).scalar_one()
    assert count == 1


def test_six_months_paid_during_grace_start_from_the_old_end(
    client: TestClient,
    admin: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    ends = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0)
    _paid(platform_session_factory, shop.company_id, ends, "past_due")
    assert _stages(datetime.now(UTC), shop.company_id) == ["due"]
    response = _pay(client, admin, shop.company_id, "29400")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "active"
    assert datetime.fromisoformat(body["current_period_end"]) == platform_service._add_months(
        ends, 6
    )
    # Les relances repartent de zéro : l'étape franchie visait l'ancienne fin, plus rien
    # n'est envoyé (horloge gardée près d'aujourd'hui : la suite partage d'autres boutiques).
    new_end = datetime.fromisoformat(body["current_period_end"])
    row = subscription_row(platform_session_factory, shop.company_id)
    assert row.reminder_for_end != new_end
    for offset in (0, 1, 2, 3):
        assert _stages(datetime.now(UTC) + timedelta(days=offset), shop.company_id) == []


def test_six_months_paid_after_the_pause_reopen_from_today(
    client: TestClient,
    admin: dict[str, str],
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    ends = datetime.now(UTC) - timedelta(days=10)
    _paid(platform_session_factory, shop.company_id, ends, "suspended")
    response = _pay(client, admin, shop.company_id, "29400")
    assert response.status_code == 201, response.text
    end = datetime.fromisoformat(response.json()["current_period_end"])
    assert timedelta(days=180) <= end - datetime.now(UTC) <= timedelta(days=185)
    assert _access(platform_session_factory, shop.company_id) == "active"
    assert subscription_row(platform_session_factory, shop.company_id).status == "active"


def test_three_months_is_still_refused(
    client: TestClient, admin: dict[str, str], shop: DemoCompany
) -> None:
    response = _pay(client, admin, shop.company_id, "14700", months=3)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


# ------------------------------------------------------------- la migration


@pytest.fixture
def alembic_config(migrated_database: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", migrated_database)
    return config


def _insert_payment(engine: Engine, subscription_id: UUID, months: int) -> None:
    """Écrit en propriétaire, sans l'API : la règle vérifiée est celle de la base."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO subscription_payments (subscription_id, amount_fcfa, paid_at, "
                "method, period_months, idempotency_key, recorded_by) VALUES (:sub, 29400, "
                "now(), 'wave', :months, :key, (SELECT min(id::text)::uuid FROM platform_users))"
            ),
            {"sub": subscription_id, "months": months, "key": f"migration-{uuid4().hex}"},
        )


def _six_month_payments(engine: Engine, subscription_id: UUID) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM subscription_payments "
                    "WHERE subscription_id = :sub AND period_months = 6"
                ),
                {"sub": subscription_id},
            ).scalar_one()
        )


def test_the_downgrade_keeps_six_month_payments_and_refuses_new_ones(
    alembic_config: Config,
    owner_engine: Engine,
    shop: DemoCompany,
    admin: dict[str, str],
    platform_session_factory: sessionmaker[Any],
) -> None:
    subscription_id = subscription_row(platform_session_factory, shop.company_id).id
    _insert_payment(owner_engine, subscription_id, 6)
    command.downgrade(alembic_config, "0044")
    try:
        with owner_engine.connect() as connection:
            columns = connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'plans' AND column_name = 'semiannual_price_fcfa'"
                )
            ).all()
        assert columns == []
        assert _six_month_payments(owner_engine, subscription_id) == 1
        with pytest.raises(IntegrityError):
            _insert_payment(owner_engine, subscription_id, 6)
    finally:
        command.upgrade(alembic_config, "head")
    _insert_payment(owner_engine, subscription_id, 6)
    assert _six_month_payments(owner_engine, subscription_id) == 2
    with owner_engine.connect() as connection:
        assert connection.execute(
            text("SELECT semiannual_price_fcfa FROM plans WHERE code = 'starter'")
        ).scalar_one() == Decimal("29400")
