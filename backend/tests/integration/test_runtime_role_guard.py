"""Garde-fou 1 de l'ADR 0042 : aucun processus ne s'exécute sous `coges_owner`.

`coges_owner` est membre de deux rôles BYPASSRLS ; s'il servait à l'exécution, un
`SET ROLE coges_auth` ouvrirait toutes les entreprises. Les engines applicatifs
refusent donc leur première connexion sous ce rôle, ou sous tout rôle BYPASSRLS.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import DBAPIError, StatementError

from app.core.database import create_app_engine
from app.core.role_guard import (
    ForbiddenRuntimeRoleError,
    assert_runtime_role,
    check_role,
)


def test_owner_dsn_is_refused_at_first_connection(migrated_database: str) -> None:
    engine = create_app_engine(migrated_database, pool_size=1, max_overflow=0)
    try:
        with pytest.raises((ForbiddenRuntimeRoleError, DBAPIError, StatementError)):
            assert_runtime_role(engine)
        # Rejoué tant qu'il échoue : l'engine reste inutilisable, il ne « passe »
        # jamais à la deuxième tentative.
        with (
            pytest.raises((ForbiddenRuntimeRoleError, DBAPIError, StatementError)),
            engine.connect(),
        ):
            pass
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["app", "relay", "analytics"])
def test_runtime_roles_are_accepted(kind: str, database_urls: tuple[str, str]) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    url = {
        "app": database_urls[1],
        "relay": settings.test_database_url_relay,
        "analytics": settings.test_database_url_analytics,
    }[kind]
    assert url
    engine = create_app_engine(url, pool_size=1, max_overflow=0)
    try:
        assert assert_runtime_role(engine) == f"coges_{kind}"
    finally:
        engine.dispose()


def test_bypassrls_role_is_refused() -> None:
    with pytest.raises(ForbiddenRuntimeRoleError, match="BYPASSRLS"):
        check_role("neondb_owner", bypass_rls=True)
    with pytest.raises(ForbiddenRuntimeRoleError, match="migrations"):
        check_role("coges_owner", bypass_rls=False)
    check_role("coges_app", bypass_rls=False)
