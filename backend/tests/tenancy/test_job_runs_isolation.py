"""Le journal des tâches ne laisse sortir aucune entreprise (ADR 0077).

`job_runs` porte un `company_id` : RLS FORCE comme toute table qui en porte (T37),
aucun privilège pour les rôles d'exécution (T36), et les deux fonctions qui la lisent
ou lisent l'outbox toutes entreprises confondues ne rendent que des agrégats.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import TenantContext, tenant_transaction
from tests.integration.ops_harness import add_run, as_ops
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.tenancy


def _result_columns(app_engine: Engine, signature: str) -> list[str]:
    with app_engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT unnest(proargnames[pronargs + 1:]) FROM pg_proc "
                    "WHERE oid = CAST(:signature AS regprocedure)"
                ),
                {"signature": signature},
            ).scalars()
        )


@pytest.mark.parametrize("signature", ["job_runs_latest(interval)", "outbox_lag()"])
def test_cross_company_functions_return_no_company_id(app_engine: Engine, signature: str) -> None:
    columns = _result_columns(app_engine, signature)
    assert columns, f"{signature} ne déclare aucune colonne"
    assert not [column for column in columns if "company" in column and column.endswith("_id")]


def test_tenant_context_does_not_open_job_runs(
    session_factory: sessionmaker[Any], owner_engine: Engine, tenant_a: Tenant
) -> None:
    """Même dans son propre contexte, une entreprise ne lit pas ses traces en direct."""
    add_run(owner_engine, "test.isolation", company_id=tenant_a.company_id)
    try:
        with (
            pytest.raises(Exception, match="permission denied"),
            tenant_transaction(
                TenantContext.bootstrap(tenant_a.company_id), session_factory=session_factory
            ) as session,
        ):
            session.execute(text("SELECT count(*) FROM job_runs"))
    finally:
        as_ops(owner_engine, "DELETE FROM job_runs WHERE job = 'test.isolation'")


def test_rls_still_scopes_job_runs_for_its_owner_role(
    owner_engine: Engine, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Sans `BYPASSRLS`, la politique tenant s'appliquerait : B ne verrait pas A."""
    add_run(owner_engine, "test.rls", company_id=tenant_a.company_id)
    try:
        with owner_engine.begin() as connection:
            # Le propriétaire de la table est soumis à FORCE RLS : avec le contexte de
            # B, il ne voit pas la trace de A.
            connection.execute(
                text("SELECT set_config('app.company_id', :company, true)"),
                {"company": str(tenant_b.company_id)},
            )
            seen = connection.execute(
                text("SELECT count(*) FROM job_runs WHERE job = 'test.rls'")
            ).scalar_one()
        assert seen == 0
    finally:
        as_ops(owner_engine, "DELETE FROM job_runs WHERE job = 'test.rls'")
