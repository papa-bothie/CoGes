"""Une erreur SQL ne laisse ni valeur liée ni e-mail dans les journaux (P2.7, ADR 0088).

SQLAlchemy recopie les paramètres liés dans le message de l'exception, et PostgreSQL y
ajoute le détail d'une violation d'unicité (« Key (company_id, email)=(…, awa@…) ») :
le tout finissait dans le journal JSON et dans Sentry, avec l'e-mail du client ou le
hachage Argon2 d'un mot de passe.
"""

from __future__ import annotations

import logging
import sys
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import create_app_engine
from app.core.logging import JsonFormatter
from app.core.observability import scrub_event
from app.core.tenancy import tenant_transaction
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

EMAIL = "awa.secret@example.com"
ARGON2 = "$argon2id$v=19$m=65536,t=3,p=4$c2VsZGVtZXI$aGFjaGFnZWR1bW90ZGVwYXNzZQ"


def _formatted(exc: BaseException) -> str:
    try:
        raise exc
    except BaseException:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "échec", None, sys.exc_info())
    return JsonFormatter().format(record)


def _sentry_event(exc: BaseException) -> dict[str, Any]:
    return {
        "message": str(exc),
        "exception": {"values": [{"type": type(exc).__name__, "value": str(exc)}]},
    }


def test_bound_parameters_never_reach_the_log(database_urls: tuple[str, str]) -> None:
    _, app_url = database_urls
    engine = create_app_engine(app_url, pool_size=1, max_overflow=0)
    try:
        with pytest.raises(DBAPIError) as raised, engine.connect() as connection:
            connection.execute(
                text("SELECT CAST(:email AS integer), :hash"), {"email": EMAIL, "hash": ARGON2}
            )
    finally:
        engine.dispose()

    line = _formatted(raised.value)
    assert EMAIL not in line, "valeur liée dans le journal"
    assert ARGON2 not in line, "hachage dans le journal"
    event = scrub_event(_sentry_event(raised.value))
    assert EMAIL not in str(event) and ARGON2 not in str(event)


def test_a_unique_violation_detail_is_masked(session_factory: Any, tenant_a: Tenant) -> None:
    """Le DETAIL de PostgreSQL cite la valeur en double : masqué partout."""
    email = f"double-{uuid4().hex[:6]}@example.com"
    insert = text(
        "INSERT INTO users (company_id, email, password_hash, full_name) "
        "VALUES (:company_id, :email, 'x', 'Double')"
    )
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        session.execute(insert, {"company_id": tenant_a.company_id, "email": email})
    with (
        pytest.raises(DBAPIError) as raised,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(insert, {"company_id": tenant_a.company_id, "email": email})

    assert email not in _formatted(raised.value)
    assert email not in str(scrub_event(_sentry_event(raised.value)))
