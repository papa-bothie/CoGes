"""Garde-fou du rôle d'exécution (ADR 0042, garde-fou 1).

`coges_owner` est membre (`WITH INHERIT FALSE`) de `coges_auth` et de `coges_bus`, deux
rôles `BYPASSRLS` : un changement de rôle explicite lui ouvrirait toutes les entreprises. Il ne
doit donc **jamais** servir à l'exécution. Ce module refuse toute connexion applicative
ouverte sous `coges_owner`, ou sous un rôle qui possède `rolbypassrls`.

La vérification est posée sur l'événement `first_connect` de chaque engine créé par
`create_app_engine` : elle s'exécute une fois par processus et par engine, que ce
processus soit l'API sur Vercel, un worker, beat ou le relais. SQLAlchemy la rejoue tant
qu'elle échoue : un engine monté sur le mauvais DSN reste inutilisable, il ne « passe »
jamais après une première erreur. Workers et relais l'appellent en plus au démarrage
(`assert_runtime_role`), pour échouer avant de consommer quoi que ce soit.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

logger = logging.getLogger(__name__)

#: Propriétaire du schéma : migrations uniquement (README-infra).
OWNER_ROLE = "coges_owner"

_ROLE_SQL = "SELECT current_user, rolbypassrls FROM pg_roles WHERE rolname = current_user"


class ForbiddenRuntimeRoleError(RuntimeError):
    """Le DSN applicatif désigne un rôle qui franchit, ou peut franchir, la RLS."""


def check_role(role: str, bypass_rls: bool) -> None:
    """Refuse `coges_owner` et tout rôle `BYPASSRLS`."""
    if role == OWNER_ROLE:
        raise ForbiddenRuntimeRoleError(
            f"Le rôle {role!r} est réservé aux migrations : l'API et les workers "
            "doivent se connecter en coges_app, coges_relay ou coges_analytics."
        )
    if bypass_rls:
        raise ForbiddenRuntimeRoleError(
            f"Le rôle {role!r} possède BYPASSRLS : il franchirait l'isolation des entreprises."
        )


def _check_dbapi_connection(dbapi_connection: Any) -> None:
    with dbapi_connection.cursor() as cursor:
        cursor.execute(_ROLE_SQL)
        role, bypass_rls = cursor.fetchone()
    # La requête a ouvert une transaction implicite : on la referme pour rendre une
    # connexion propre au pool.
    dbapi_connection.rollback()
    check_role(role, bool(bypass_rls))


def install_role_guard(engine: Engine) -> None:
    """Vérifie le rôle à la première connexion de l'engine."""

    @sa_event.listens_for(engine, "first_connect")
    def _guard(dbapi_connection: Any, connection_record: Any) -> None:
        try:
            _check_dbapi_connection(dbapi_connection)
        except ForbiddenRuntimeRoleError:
            logger.critical("Connexion refusée : rôle d'exécution interdit", exc_info=True)
            raise


def assert_runtime_role(engine: Engine) -> str:
    """Ouvre une connexion et vérifie le rôle, pour échouer dès le démarrage."""
    with engine.connect() as connection:
        role, bypass_rls = connection.execute(text(_ROLE_SQL)).one()
    check_role(str(role), bool(bypass_rls))
    return str(role)
