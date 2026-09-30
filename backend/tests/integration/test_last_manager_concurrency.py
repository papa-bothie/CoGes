"""Garde du dernier gérant sous concurrence (ADR 0054).

Deux gérants, A et B. A désactive B pendant que B désactive A. Sans verrou, chacun lit
l'autre comme « encore actif », les deux retraits passent, et l'entreprise n'a plus aucun
gérant actif — le défaut observé : trois titulaires du rôle, zéro actif.

Comme T28 et T38, le test ne **court** pas après la fenêtre de concurrence, il la
**provoque** : il tient lui-même le verrou de la garde, lance les deux retraits, attend
qu'ils soient **tous deux** bloqués au rendez-vous — donc tous deux ouverts, cible lue —
puis relâche. Sans le verrou, les deux passeraient et l'attente échouerait.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.rbac import service as rbac_service
from app.modules.rbac.matrix import MANAGER
from app.modules.users import service as users_service
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserUpdate
from tests.conftest import (
    _create_demo_company,
    auth_headers,
    create_user_with_role,
    login_token,
)

pytestmark = pytest.mark.integration

#: Un retrait : (session, contexte de l'auteur, identifiant du gérant visé).
Removal = Callable[[Session, TenantContext, UUID], object]


def _patch(session: Session, ctx: TenantContext, target: UUID) -> object:
    return users_service.update_user(session, ctx, target, UserUpdate(is_active=False))


def _delete(session: Session, ctx: TenantContext, target: UUID) -> object:
    return users_service.deactivate_user(session, ctx, target)


def _revoke(session: Session, ctx: TenantContext, target: UUID) -> object:
    role_id = rbac_service.system_role_id(session, ctx, MANAGER)
    assert role_id is not None
    return users_service.revoke_role(session, ctx, target, role_id)


def _wait_for_blocked_guards(session: Session, expected: int, timeout: float = 10.0) -> None:
    """Attend que `expected` transactions attendent un verrou consultatif."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        waiting = session.execute(
            text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
        ).scalar_one()
        if waiting >= expected:
            return
        time.sleep(0.05)
    raise AssertionError(f"les {expected} retraits devaient attendre le verrou de la garde")


def _active_managers(session_factory: sessionmaker[Any], ctx: TenantContext) -> int:
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        role_id = rbac_service.system_role_id(session, ctx, MANAGER)
        assert role_id is not None
        holders = rbac_service.holders_of_role(session, ctx, role_id)
        return len(users_service.active_among(session, ctx, holders))


@pytest.mark.parametrize(
    "removal", [_patch, _delete, _revoke], ids=["patch-is-active", "delete", "revoke-role"]
)
def test_two_managers_removing_each_other_leave_one_active(
    api_client: TestClient,
    concurrent_session_factory: sessionmaker[Any],
    removal: Removal,
) -> None:
    company = _create_demo_company(f"course-{uuid4().hex[:8]}")
    token = login_token(api_client, company)
    email = f"second@{company.slug}.example.com"
    create_user_with_role(api_client, token, company, role="gerant", email=email)
    second = next(
        UUID(user["id"])
        for user in api_client.get("/api/v1/users", headers=auth_headers(token)).json()["items"]
        if user["email"] == email
    )
    first = company.manager_id
    ctx_of = {
        user: TenantContext(user_id=user, company_id=company.company_id) for user in (first, second)
    }
    assert _active_managers(concurrent_session_factory, ctx_of[first]) == 2

    def remove(author: UUID, target: UUID) -> str:
        """Un gérant qui retire l'autre ; renvoie le code du refus, ou « succès »."""
        try:
            with tenant_transaction(
                ctx_of[author], session_factory=concurrent_session_factory
            ) as session:
                removal(session, ctx_of[author], target)
        except users_service.LastManagerError as exc:
            return exc.code
        return "succès"

    with ThreadPoolExecutor(max_workers=2) as pool:
        with tenant_transaction(
            ctx_of[first], session_factory=concurrent_session_factory
        ) as session:
            # 1. Le test prend le verrou de la garde : les deux retraits s'y arrêteront.
            UserRepository(session, ctx_of[first]).lock_manager_guard()
            # 2. Les deux retraits croisés partent, puis attendent tous deux au rendez-vous.
            futures = [pool.submit(remove, first, second), pool.submit(remove, second, first)]
            _wait_for_blocked_guards(session, expected=2)
        # 3. Le COMMIT relâche le verrou : ils passent l'un après l'autre.
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == ["last_manager", "succès"], outcomes
    assert _active_managers(concurrent_session_factory, ctx_of[first]) == 1
