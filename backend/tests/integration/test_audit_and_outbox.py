"""Audit critique et outbox transactionnelle.

Les deux mécanismes partagent la même garantie : ils vivent **dans** la transaction
métier. Si elle tombe, ils tombent avec elle ; si elle passe, ils sont là.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.audit import AuditAction, audit_critical
from app.core.events.outbox import emit
from app.core.events.types import EVENT_TYPES, EventType
from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant

pytestmark = pytest.mark.integration


def _audit_count(session_factory: sessionmaker[Any], company: DemoCompany, entity_id: str) -> int:
    return int(
        read_scalar_in_tenant(
            session_factory,
            company.company_id,
            "SELECT count(*) FROM audit_logs WHERE entity_id = :id",
            {"id": entity_id},
        )
    )


def test_audit_is_lost_when_the_transaction_rolls_back(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    """Une opération annulée ne laisse **aucune** trace : pas d'audit sans fait."""
    entity_id = uuid4()
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)

    with (
        pytest.raises(RuntimeError, match="échec simulé"),
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        audit_critical(
            session,
            ctx,
            action=AuditAction.UPDATE,
            entity_table="roles",
            entity_id=entity_id,
            before={"name": "avant"},
            after={"name": "après"},
        )
        raise RuntimeError("échec simulé après l'écriture d'audit")

    assert _audit_count(session_factory, company_alpha, str(entity_id)) == 0


def test_audit_is_written_exactly_once_on_commit(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    """Une opération validée laisse **une** ligne, avec l'avant et l'après."""
    entity_id = uuid4()
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)

    with tenant_transaction(ctx, session_factory=session_factory) as session:
        audit_critical(
            session,
            ctx,
            action=AuditAction.UPDATE,
            entity_table="roles",
            entity_id=entity_id,
            before={"name": "avant"},
            after={"name": "après"},
            ip_address="192.0.2.10",
        )

    assert _audit_count(session_factory, company_alpha, str(entity_id)) == 1

    diff = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT diff FROM audit_logs WHERE entity_id = :id",
        {"id": entity_id},
    )
    assert diff == {"before": {"name": "avant"}, "after": {"name": "après"}}


def test_role_change_through_the_api_is_audited(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Le changement de rôle écrit sa trace, et elle survit à la requête."""
    created = api_client.post(
        "/api/v1/roles",
        headers=auth_headers(alpha_token),
        json={"name": f"role-audite-{uuid4().hex[:6]}", "permissions": ["dashboard:read"]},
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]

    assert _audit_count(session_factory, company_alpha, role_id) == 1


def test_sensitive_company_setting_change_is_audited(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Changer la devise change l'interprétation de toutes les données suivantes."""
    before = _audit_count(session_factory, company_alpha, str(company_alpha.company_id))

    response = api_client.patch(
        "/api/v1/companies/me",
        headers=auth_headers(alpha_token),
        json={"settings": {"vat_enabled": True, "low_stock_threshold": 5}},
    )
    assert response.status_code == 200, response.text

    assert _audit_count(session_factory, company_alpha, str(company_alpha.company_id)) == before + 1


def test_audit_log_cannot_be_updated_by_the_application(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    """Append-only : `coges_app` n'a pas le droit de réécrire une trace."""
    ctx = TenantContext.bootstrap(company_alpha.company_id)

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(text("UPDATE audit_logs SET action = 'insert'"))

    assert "permission denied" in str(excinfo.value).lower()


def test_outbox_event_is_written_in_the_transaction(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    """L'événement est écrit avec la donnée, et reste **non publié**."""
    aggregate_id = uuid4()
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)

    with tenant_transaction(ctx, session_factory=session_factory) as session:
        emit(
            session,
            ctx,
            event_type=EventType.STOCK_UPDATED,
            aggregate_type="product",
            aggregate_id=aggregate_id,
            payload={"quantity": "3.000"},
        )

    published = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT published_at IS NULL FROM business_events WHERE aggregate_id = :id",
        {"id": aggregate_id},
    )
    assert published is True, "l'événement ne doit être publié qu'après COMMIT, par le relais"


def test_outbox_event_disappears_with_a_rollback(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    aggregate_id = uuid4()
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)

    with (
        pytest.raises(RuntimeError),
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        emit(
            session,
            ctx,
            event_type=EventType.SALE_CONFIRMED,
            aggregate_type="sale",
            aggregate_id=aggregate_id,
            payload={},
        )
        raise RuntimeError("échec simulé")

    count = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM business_events WHERE aggregate_id = :id",
        {"id": aggregate_id},
    )
    assert count == 0


def test_database_refuses_an_event_type_outside_the_closed_list(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    """La liste des 10 événements est fermée **en base**, pas seulement en Python."""
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO business_events "
                "(company_id, event_type, aggregate_type, aggregate_id, payload) "
                "VALUES (:company_id, 'sale.invented', 'sale', :aggregate_id, '{}'::jsonb)"
            ),
            {"company_id": company_alpha.company_id, "aggregate_id": uuid4()},
        )

    assert "check constraint" in str(excinfo.value).lower()


def test_python_and_database_share_the_same_event_list(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    """Les dix types acceptés en base sont exactement ceux de `EventType`."""
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)

    with tenant_transaction(ctx, session_factory=session_factory) as session:
        constraint = session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'business_events'::regclass AND contype = 'c' "
                "AND pg_get_constraintdef(oid) LIKE '%event_type%'"
            )
        ).scalar_one()

    for event_type in EVENT_TYPES:
        assert f"'{event_type}'" in constraint, f"{event_type} absent du CHECK en base"
    assert len(EVENT_TYPES) == 10
