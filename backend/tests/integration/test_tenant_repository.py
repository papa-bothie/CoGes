"""Barrière 2 — le repository de base filtre par tenant et refuse les écritures croisées.

Ces tests utilisent un modèle ORM provisoire cartographié sur `roles` : les modèles
métier appartiennent aux modules, qui arrivent en phase 02.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.core.database import IdentifiedTenantBase
from app.core.errors import TenantIsolationError
from app.core.repository import MAX_PAGE_SIZE, TenantRepository
from app.core.tenancy import tenant_transaction
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration


class RoleRow(IdentifiedTenantBase):
    """Modèle provisoire, remplacé par `app.modules.rbac.models` en phase 02."""

    __tablename__ = "roles"
    __table_args__ = {"extend_existing": True}

    name: Mapped[str] = mapped_column()
    is_system: Mapped[bool] = mapped_column()


class RoleRepository(TenantRepository[RoleRow]):
    model = RoleRow


def test_reads_are_scoped_to_the_context_tenant(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        repository = RoleRepository(session, tenant_a.ctx)
        rows = repository.page()
        own = repository.get(tenant_a.role_id)
        foreign = repository.get(tenant_b.role_id)
        total = repository.count()

    assert {row.company_id for row in rows} == {tenant_a.company_id}
    assert own is not None
    assert foreign is None, "le repository a renvoyé le rôle d'une autre entreprise"
    assert total == len(rows)


def test_add_stamps_the_context_company_id(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    created_id = uuid4()
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        repository = RoleRepository(session, tenant_a.ctx)
        repository.add(RoleRow(id=created_id, name=f"role-{created_id.hex[:8]}", is_system=False))

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        stored = RoleRepository(session, tenant_a.ctx).get(created_id)
        assert stored is not None
        assert stored.company_id == tenant_a.company_id


def test_add_refuses_a_foreign_company_id(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """La barrière applicative donne un message métier là où la RLS renverrait 42501."""
    with (
        pytest.raises(TenantIsolationError),
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        repository = RoleRepository(session, tenant_a.ctx)
        repository.add(
            RoleRow(id=uuid4(), company_id=tenant_b.company_id, name="intrus", is_system=False)
        )


def test_pagination_bounds_are_enforced(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        repository = RoleRepository(session, tenant_a.ctx)
        with pytest.raises(ValueError, match="page doit être"):
            repository.page(page=0)
        with pytest.raises(ValueError, match="page_size doit être"):
            repository.page(page_size=MAX_PAGE_SIZE + 1)
