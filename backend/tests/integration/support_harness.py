"""Sessions d'accès support pour les tests (ADR 0092).

Ouvertes directement sous `coges_app_platform`, comme le ferait la route, quand le test
ne porte pas sur l'ouverture elle-même : isolation, lecture seule, échéance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.security import create_support_access_token

_INSERT = text(
    """
    INSERT INTO support_sessions
        (company_id, platform_user_id, justification, started_at, expires_at)
    VALUES (:company_id, :platform_user_id, 'Le gérant signale un écart de caisse',
            :started_at, :expires_at)
    RETURNING id
    """
)


def open_support_session(
    platform_session_factory: sessionmaker[Any],
    company_id: UUID,
    platform_user_id: UUID,
    *,
    started_at: datetime | None = None,
    duration: timedelta = timedelta(hours=2),
    token_expires_at: datetime | None = None,
) -> tuple[UUID, str]:
    """Insère une session et rend (id, jeton). `token_expires_at` découple l'échéance du
    jeton de celle de la session, pour prouver que la base est relue à chaque requête."""
    start = started_at or datetime.now(UTC)
    with platform_session_factory.begin() as session:
        session_id = session.execute(
            _INSERT,
            {
                "company_id": company_id,
                "platform_user_id": platform_user_id,
                "started_at": start,
                "expires_at": start + duration,
            },
        ).scalar_one()
    token, _ = create_support_access_token(
        session_id, company_id, token_expires_at or start + duration
    )
    return session_id, token


def close_support_session(platform_session_factory: sessionmaker[Any], session_id: UUID) -> None:
    with platform_session_factory.begin() as session:
        session.execute(
            text(
                """
                UPDATE support_sessions SET ended_at = now() WHERE id = :id
                """
            ),
            {"id": session_id},
        )
