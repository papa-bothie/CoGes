"""T34 — un insight écarté ne bloque pas la réémission de sa `dedupe_key`.

Attaque la base directement : l'index partiel `insights_dedupe_uq` (`WHERE status <>
'dismissed'`) refuse un doublon vivant et accepte une réémission après écartement.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from tests.integration import intelligence_harness as ih

pytestmark = pytest.mark.integration

INSERT = text(
    """
    INSERT INTO insights (company_id, insight_type, severity, title, dedupe_key)
    VALUES (:company_id, 'slow_mover', 'info', 'Écoulement lent — Parapluie', :key)
    """
)


def test_t34_a_dismissed_insight_lets_the_same_key_be_reissued(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> None:
    shop = ih.new_shop("t34")
    key = f"slow_mover:{uuid4()}:2026-W39"
    params = {"company_id": shop.company_id, "key": key}

    with ih.write(analytics_session_factory, shop) as session:
        session.execute(INSERT, params)

    # Doublon vivant : refusé par l'index partiel.
    with pytest.raises(IntegrityError), ih.write(analytics_session_factory, shop) as session:
        session.execute(INSERT, params)

    # L'utilisateur écarte l'insight — sous `coges_app`, seul `status` et ses dates.
    with ih.write(session_factory, shop) as session:
        session.execute(
            text(
                "UPDATE insights SET status = 'dismissed', read_at = now() WHERE dedupe_key = :key"
            ),
            {"key": key},
        )

    # Réémission : acceptée, une seconde ligne naît.
    with ih.write(analytics_session_factory, shop) as session:
        session.execute(INSERT, params)

    statuses = ih.rows(
        analytics_session_factory,
        shop,
        "SELECT status FROM insights WHERE dedupe_key = :key ORDER BY generated_at",
        key=key,
    )
    assert [row.status for row in statuses] == ["dismissed", "new"]
