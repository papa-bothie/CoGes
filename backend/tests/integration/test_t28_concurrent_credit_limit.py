"""T28 sous concurrence — deux crédits simultanés ne franchissent pas le plafond.

Le § 5.5 exige que « Σ des soldes ouverts du client reste sous `customers.credit_limit` ».
Une vérification qui lit puis somme **sans verrou** ne tient pas cette promesse : deux
transactions concurrentes lisent toutes les deux un encours de 0, concluent toutes les deux que
le crédit passe, et le client se retrouve engagé au double de son plafond. Aucune contrainte
déclarative ne peut rattraper cela — la règle porte sur une **somme de lignes**, pas sur une
ligne.

D'où le verrou sur la ligne client, dans `debt_credit_limit()` (révision 0007). Il ne protège
pas `customers` — que personne ne modifie ici — il sert de **point de rendez-vous** : deux
ouvertures de dette pour le même client s'y sérialisent, et la seconde somme un encours qui
contient déjà la première.

Comme T38, le test ne **court** pas après la fenêtre de concurrence, il la **provoque**.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.database import create_app_engine
from app.core.errors import sqlstate
from app.core.tenancy import tenant_transaction
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: SQLSTATE applicatif du plafond de crédit (révision 0006, ADR 0023).
CREDIT_LIMIT_EXCEEDED = "CG030"


@pytest.fixture
def concurrent_session_factory(
    migrated_database: str, database_urls: tuple[str, str]
) -> Iterator[sessionmaker[Any]]:
    """Fabrique de sessions sur un pool de **trois** connexions.

    Le pool de la suite n'en contient qu'une — c'est ce qu'exige T4. Il en faut trois
    ici : une pour le verrou tenu par le test, deux pour les caisses concurrentes.
    """
    _, app_url = database_urls
    engine: Engine = create_app_engine(app_url, pool_size=3, max_overflow=0)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()


def _make_customer(
    session_factory: sessionmaker[Any], tenant: Tenant, *, credit_limit: str
) -> UUID:
    """Un client neuf, avec son plafond. Les clients du harnais sont partagés."""
    customer_id = uuid4()
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO customers (id, company_id, code, name, credit_limit) "
                "VALUES (:id, :company_id, :code, :name, :credit_limit)"
            ),
            {
                "id": customer_id,
                "company_id": tenant.company_id,
                "code": f"CLI-{customer_id.hex[:8]}",
                "name": f"Client sous plafond {customer_id.hex[:6]}",
                "credit_limit": Decimal(credit_limit),
            },
        )
    return customer_id


def test_t28_two_concurrent_credits_cannot_exceed_the_limit(
    concurrent_session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Plafond 1 000, deux dettes de 800 en parallèle : une passe, l'autre lève `CG030`."""
    customer_id = _make_customer(concurrent_session_factory, tenant_a, credit_limit="1000.00")

    def open_credit(_: int) -> str:
        """Une caisse qui ouvre une dette de 800 pour ce client."""
        try:
            with tenant_transaction(
                tenant_a.ctx, session_factory=concurrent_session_factory
            ) as session:
                session.execute(
                    text(
                        "INSERT INTO debts (company_id, party_type, customer_id, principal) "
                        "VALUES (:company_id, 'customer', :customer_id, 800.00)"
                    ),
                    {"company_id": tenant_a.company_id, "customer_id": customer_id},
                )
        except DBAPIError as exc:
            assert sqlstate(exc) == CREDIT_LIMIT_EXCEEDED, str(exc)
            return "refus"
        return "succès"

    with ThreadPoolExecutor(max_workers=2) as pool:
        with tenant_transaction(
            tenant_a.ctx, session_factory=concurrent_session_factory
        ) as session:
            # 1. Le test s'approprie la ligne client : les deux caisses vont
            #    s'arrêter exactement là où le trigger prend son verrou.
            session.execute(
                text("SELECT credit_limit FROM customers WHERE id = :id FOR UPDATE"),
                {"id": customer_id},
            )
            # 2. Les deux ouvertures de crédit partent et se bloquent.
            futures = [pool.submit(open_credit, index) for index in range(2)]
        # 3. Le COMMIT relâche le verrou : les deux reprennent, l'une après l'autre.
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == ["refus", "succès"], f"exactement un crédit doit passer, obtenu : {outcomes}"

    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        outstanding = session.execute(
            text(
                "SELECT coalesce(sum(balance), 0) FROM debts "
                " WHERE customer_id = :id AND status IN ('open','partially_paid')"
            ),
            {"id": customer_id},
        ).scalar_one()
        opened = session.execute(
            text("SELECT count(*) FROM debts WHERE customer_id = :id"), {"id": customer_id}
        ).scalar_one()

    assert outstanding == Decimal("800.00"), "l'encours ne doit jamais dépasser le plafond"
    assert opened == 1, "la dette refusée ne doit laisser aucune trace"


def test_t28_the_limit_still_counts_debts_opened_one_after_another(
    concurrent_session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Le verrou n'a rien changé au cas simple : deux dettes successives cumulent bien."""
    customer_id = _make_customer(concurrent_session_factory, tenant_a, credit_limit="1000.00")

    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        session.execute(
            text(
                "INSERT INTO debts (company_id, party_type, customer_id, principal) "
                "VALUES (:company_id, 'customer', :customer_id, 800.00)"
            ),
            {"company_id": tenant_a.company_id, "customer_id": customer_id},
        )

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO debts (company_id, party_type, customer_id, principal) "
                "VALUES (:company_id, 'customer', :customer_id, 800.00)"
            ),
            {"company_id": tenant_a.company_id, "customer_id": customer_id},
        )

    assert sqlstate(excinfo.value) == CREDIT_LIMIT_EXCEEDED
    assert "Plafond de credit depasse" in str(excinfo.value)


def test_t28_a_customer_without_a_limit_is_never_blocked(
    concurrent_session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """`credit_limit IS NULL` veut dire « aucune limite », et le verrou ne le change pas.

    La distinction compte : `NULL` n'est pas `0`. Un plafond à zéro interdit tout
    crédit, une absence de plafond n'en interdit aucun.
    """
    customer_id = uuid4()
    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        session.execute(
            text(
                "INSERT INTO customers (id, company_id, code, name) "
                "VALUES (:id, :company_id, :code, 'Client sans plafond')"
            ),
            {
                "id": customer_id,
                "company_id": tenant_a.company_id,
                "code": f"CLI-{customer_id.hex[:8]}",
            },
        )
        for _ in range(3):
            session.execute(
                text(
                    "INSERT INTO debts (company_id, party_type, customer_id, principal) "
                    "VALUES (:company_id, 'customer', :customer_id, 500000.00)"
                ),
                {"company_id": tenant_a.company_id, "customer_id": customer_id},
            )

    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        opened = session.execute(
            text("SELECT count(*) FROM debts WHERE customer_id = :id"), {"id": customer_id}
        ).scalar_one()
    assert opened == 3


def test_the_credit_limit_trigger_keeps_the_privilege_it_needs(owner_engine: Engine) -> None:
    """`coges_app` doit garder `UPDATE` sur `customers`, sinon plus aucun crédit ne passe.

    `SELECT … FOR UPDATE` exige le privilège `UPDATE` en plus de `SELECT`. Le réflexe
    de durcissement — retirer `UPDATE` sur une table qu'un trigger ne modifie pas —
    casserait `debt_credit_limit()` en `permission denied`, et avec lui toute vente à
    crédit. La leçon est celle de l'ADR 0018, décision 3, apprise sur
    `inventory_movements` ; ce test la rend non régressive ici aussi.
    """
    with owner_engine.begin() as connection:
        granted = connection.execute(
            text(
                "SELECT has_table_privilege('coges_app', 'customers', 'SELECT') AS can_select,"
                "       has_table_privilege('coges_app', 'customers', 'UPDATE') AS can_update"
            )
        ).one()

    assert granted.can_select, "le trigger lit `customers`"
    assert granted.can_update, (
        "`SELECT … FOR UPDATE` sur `customers` exige UPDATE : sans lui, "
        "`debt_credit_limit()` échoue en permission denied et aucune vente à crédit ne passe"
    )
