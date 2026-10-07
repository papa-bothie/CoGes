"""Le seed de la maquette ne laisse aucune date après l'heure figée (ADR 0065).

Le serveur date lui-même l'encaissement d'une confirmation, une sortie de stock, une
dette, une ligne d'audit… à l'heure du remplissage. Sans recalage, la caisse du
6 octobre serait vide et ces lignes tomberaient le jour où l'on lance le seed. Ce test
sème l'entreprise entière (une bonne minute), puis lit **toutes** les colonnes de date
des tables de l'entreprise, sous le rôle propriétaire et dans son seul contexte.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from _pytest.monkeypatch import MonkeyPatch
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import sessionmaker

from app.seed_maquette import FROZEN_NOW, RESTAMPED_TABLES, seed

pytestmark = pytest.mark.integration

#: Dates futures par nature, que personne n'a posées « pendant le remplissage » :
#: échéances, expirations, horizons.
FUTURE_BY_DESIGN = {
    ("debts", "due_date"),
    ("auth_sessions", "expires_at"),
    ("idempotency_keys", "expires_at"),
    ("export_files", "expires_at"),
    ("insights", "valid_until"),
    ("forecasts", "horizon_date"),
}

_DATE_COLUMNS = text(
    "SELECT c.table_name, c.column_name, c.data_type FROM information_schema.columns c"
    " JOIN pg_class t ON t.relname = c.table_name AND NOT t.relispartition"
    " WHERE c.table_schema = 'public'"
    " AND c.data_type IN ('timestamp with time zone', 'date')"
    " AND (c.table_name = 'companies' OR EXISTS ("
    "   SELECT 1 FROM information_schema.columns k WHERE k.table_schema = 'public'"
    "   AND k.table_name = c.table_name AND k.column_name = 'company_id'))"
    " ORDER BY 1, 2"
)


@pytest.fixture(scope="module")
def maquette(
    app_bound_to_test_database: None,
    owner_engine: Engine,
    analytics_session_factory: sessionmaker[Any],
) -> Iterator[UUID]:
    patcher = MonkeyPatch()
    patcher.setattr(
        "app.core.database.get_analytics_session_factory", lambda: analytics_session_factory
    )
    try:
        yield seed(slug=f"maquette-{uuid4().hex[:8]}", owner_engine=owner_engine)
    finally:
        patcher.undo()


@pytest.fixture
def owner(owner_engine: Engine, maquette: UUID) -> Iterator[Connection]:
    """Connexion propriétaire dans le contexte de la seule entreprise de la maquette."""
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :co, true)"), {"co": str(maquette)}
        )
        yield connection


def test_no_maquette_timestamp_is_after_the_frozen_moment(owner: Connection) -> None:
    late: list[str] = []
    for table, column, data_type in owner.execute(_DATE_COLUMNS):
        if (table, column) in FUTURE_BY_DESIGN:
            continue
        limit = FROZEN_NOW.date() if data_type == "date" else FROZEN_NOW
        count = owner.execute(
            text(f"SELECT count(*) FROM {table} WHERE {column} > :limit"), {"limit": limit}
        ).scalar_one()
        if count:
            late.append(f"{table}.{column} : {count} ligne(s)")
    assert late == [], "Horodatages après COGES_FROZEN_NOW :\n" + "\n".join(late)


def test_each_line_keeps_the_time_of_its_operation(owner: Connection) -> None:
    # L'encaissement d'une confirmation, la sortie de stock et la dette d'une vente
    # tombent à l'heure de la vente.
    assert (
        owner.execute(
            text(
                "SELECT count(*) FROM payments p JOIN sales s ON s.id = p.sale_id"
                " WHERE p.reversal_of_payment_id IS NULL AND p.paid_at <> s.sold_at"
            )
        ).scalar_one()
        == 0
    )
    assert (
        owner.execute(
            text(
                "SELECT count(*) FROM inventory_movements m"
                " JOIN sale_items i ON i.id = m.ref_id JOIN sales s ON s.id = i.sale_id"
                " WHERE m.type = 'sale_out' AND m.occurred_at <> s.sold_at"
            )
        ).scalar_one()
        == 0
    )
    assert (
        owner.execute(
            text(
                "SELECT count(*) FROM debts d JOIN sales s ON s.id = d.sale_id"
                " WHERE d.created_at <> s.sold_at"
            )
        ).scalar_one()
        == 0
    )
    # La caisse du jour figé : les 14 ventes de 87 500 F, encaissées le 6 octobre.
    inflow_today = owner.execute(
        text(
            "SELECT count(*) FROM payments p JOIN sales s ON s.id = p.sale_id"
            " WHERE s.status = 'confirmed' AND p.paid_at::date = :day"
        ),
        {"day": FROZEN_NOW.date()},
    ).scalar_one()
    assert inflow_today > 0


def test_triggers_are_back_on(owner: Connection) -> None:
    disabled = (
        owner.execute(
            text(
                "SELECT tgrelid::regclass::text || '.' || tgname FROM pg_trigger"
                " WHERE NOT tgisinternal AND tgenabled = 'D'"
                " AND tgrelid::regclass::text = ANY(:tables)"
            ),
            {"tables": list(RESTAMPED_TABLES)},
        )
        .scalars()
        .all()
    )
    assert disabled == []
