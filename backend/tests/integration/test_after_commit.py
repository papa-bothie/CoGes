"""Rappels après COMMIT (`app.core.tenancy.on_commit`, ADR 0061).

Un cache vidé avant le COMMIT peut être rempli de nouveau par une lecture qui ne voit
pas encore l'écriture ; vidé après un ROLLBACK, il ferait recalculer pour rien. Le
rappel ne se joue donc qu'une fois la transaction validée, et son échec ne remonte
jamais : l'écriture, elle, a eu lieu.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import TenantContext, on_commit, tenant_transaction
from tests.conftest import DemoCompany

pytestmark = pytest.mark.integration


def _ctx(company: DemoCompany) -> TenantContext:
    return TenantContext(user_id=company.manager_id, company_id=company.company_id)


def test_the_callback_runs_after_commit(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    calls: list[str] = []
    with tenant_transaction(_ctx(company_alpha), session_factory=session_factory) as session:
        on_commit(session, lambda: calls.append("après"))
        assert calls == [], "rien n'est joué tant que la transaction est ouverte"
    assert calls == ["après"]


def test_the_callback_never_runs_after_a_rollback(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    calls: list[str] = []
    marker = uuid4().hex
    with (
        pytest.raises(RuntimeError, match=marker),
        tenant_transaction(_ctx(company_alpha), session_factory=session_factory) as session,
    ):
        on_commit(session, lambda: calls.append("après"))
        raise RuntimeError(marker)
    assert calls == []


def test_a_failing_callback_does_not_fail_the_committed_transaction(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    calls: list[str] = []

    def boom() -> None:
        raise RuntimeError("Redis tombé")

    with tenant_transaction(_ctx(company_alpha), session_factory=session_factory) as session:
        on_commit(session, boom)
        on_commit(session, lambda: calls.append("suivant"))
    assert calls == ["suivant"]
