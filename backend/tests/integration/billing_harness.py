"""Outils des tests d'abonnement (ADR 0091).

`subscriptions` est sous RLS FORCE et fermée à `coges_app` : les tests changent l'offre
d'une entreprise sous `coges_app_platform`, comme l'administration. Le palier « sur
devis » (plafond NULL) n'existe pas dans le seed : `unlimited_plan` l'ajoute, en
propriétaire, le temps d'un test.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

UNLIMITED = "sur_devis"


def set_subscription(
    platform_session_factory: sessionmaker[Any], company_id: UUID, **values: Any
) -> None:
    """Pose des colonnes de l'abonnement ; `plan` est un code d'offre."""
    assignments: list[str] = []
    params: dict[str, Any] = {"company_id": company_id}
    for column, value in values.items():
        if column == "plan":
            assignments.append("plan_id = (SELECT id FROM plans WHERE code = :plan)")
        else:
            assignments.append(f"{column} = :{column}")
        params[column] = value
    session = platform_session_factory()
    try:
        session.execute(
            text(
                f"UPDATE subscriptions SET {', '.join(assignments)} WHERE company_id = :company_id"
            ),
            params,
        )
        session.commit()
    finally:
        session.close()


def subscription_row(platform_session_factory: sessionmaker[Any], company_id: UUID) -> Any:
    session = platform_session_factory()
    try:
        return session.execute(
            text(
                "SELECT s.*, p.code AS plan_code FROM subscriptions s "
                "JOIN plans p ON p.id = s.plan_id WHERE s.company_id = :company_id"
            ),
            {"company_id": company_id},
        ).one()
    finally:
        session.close()


def trial_ends_in(
    platform_session_factory: sessionmaker[Any], company_id: UUID, ends: datetime
) -> None:
    set_subscription(
        platform_session_factory,
        company_id,
        status="trial",
        trial_ends_at=ends,
        trial_warned_days=None,
    )


@contextmanager
def unlimited_plan(owner_engine: Engine) -> Iterator[str]:
    """Le palier « sur devis » de l'ADR 0091 : plafond NULL, non vendable."""
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO plans (code, name, price_fcfa, max_users, is_orderable) "
                "VALUES (:code, 'Sur devis', NULL, NULL, false) ON CONFLICT (code) DO NOTHING"
            ),
            {"code": UNLIMITED},
        )
    yield UNLIMITED
