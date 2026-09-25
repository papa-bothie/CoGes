"""Une tâche d'une entreprise n'écrit jamais chez une autre.

Le chemin asynchrone est l'endroit où l'isolation est la plus facile à perdre. Un
`company_id` y voyage dans un message JSON, sans utilisateur connecté, sans requête
HTTP, sans jeton — donc sans aucune des barrières qui protègent l'API. Et une tâche
se trompe de tenant en silence : personne ne consulte le tableau de bord d'un worker.

La protection est la même que partout ailleurs, et c'est tout l'intérêt : chaque
tâche ouvre sa transaction par `tenant_transaction`, la voie unique du projet, donc
sous la RLS. Ces tests lancent les tâches d'une entreprise et vérifient, **en
attaquant la base**, qu'aucune ligne de la voisine n'a bougé.

Deux tâches sont inter-entreprises par construction et méritent d'être nommées : le
relais, qui lit `business_events` sans filtre de tenant (T40), et les éventails
nocturnes, qui énumèrent les entreprises pour enfiler **une sous-tâche par tenant**.
L'énumération ne rend que des identifiants : aucune donnée métier ne la franchit.
"""

from __future__ import annotations

import datetime as dt
import itertools
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.events.inbox import Event
from app.core.events.types import EventType
from app.core.tenancy import tenant_transaction
from app.modules.inventory.events import stock_updated_payload
from app.modules.sales.events import AGGREGATE_TYPE as SALE_AGGREGATE
from app.workers.tasks.analytics import rebuild_recent_facts, rebuild_sale_day
from app.workers.tasks.notifications import on_stock_updated, scan_due_debts
from app.workers.tenants import active_company_ids
from tests.integration import facts_harness as facts
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.tenancy

#: Identifiants synthétiques : `processed_events` ne référence pas `business_events`.
_ids = itertools.count(930_000_000)

#: Tout ce qu'une tâche de la phase 08 peut écrire. Un état complet de B avant et
#: après, comparé ligne à ligne : une écriture parasite, quelle qu'elle soit, se voit.
WRITABLE_TABLES = ("daily_sales_facts", "notifications", "processed_events", "product_stock")


def _snapshot(
    session_factory: sessionmaker[Any], tenant: Tenant
) -> dict[str, list[tuple[Any, ...]]]:
    """Contenu intégral des tables qu'une tâche pourrait toucher, chez ce tenant.

    Lu **sous son propre contexte** : c'est la seule façon de voir ses lignes, la RLS
    étant forcée jusque pour le propriétaire. On compare des lignes entières et non
    des compteurs — une mise à jour parasite ne change aucun compte.
    """
    state: dict[str, list[tuple[Any, ...]]] = {}
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        for table in WRITABLE_TABLES:
            rows = session.execute(text(f"SELECT * FROM {table}")).all()
            state[table] = sorted(tuple(str(value) for value in row) for row in rows)
    return state


def _stock_event(tenant: Tenant, product_id: UUID) -> Event:
    return Event(
        id=next(_ids),
        company_id=tenant.company_id,
        event_type=EventType.STOCK_UPDATED,
        aggregate_type="product",
        aggregate_id=product_id,
        payload=stock_updated_payload(
            product_id=product_id,
            qty_on_hand=Decimal("0.000"),
            avg_cost=Decimal("600.0000"),
            movement_id=uuid4(),
            below_reorder_point=True,
        ),
        occurred_at=dt.datetime.now(dt.UTC),
    )


def _sale_event(tenant: Tenant, sale_id: UUID) -> Event:
    now = dt.datetime.now(dt.UTC)
    return Event(
        id=next(_ids),
        company_id=tenant.company_id,
        event_type=EventType.SALE_CONFIRMED,
        aggregate_type=SALE_AGGREGATE,
        aggregate_id=sale_id,
        payload={"sale_no": "V-000001", "sold_at": now.isoformat(), "total": "1000.00"},
        occurred_at=now,
    )


def test_an_event_consumer_of_a_writes_nothing_in_b(
    workers_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    tenant_a: Tenant,
    tenant_b: Tenant,
) -> None:
    """Alerte de stock et reconstruction des faits, lancées sur A : B ne bouge pas."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = facts.extra_product(session, tenant_a, f"ISOL-{uuid4().hex[:6]}")
        sale_id, _ = facts.sold_line(session, tenant_a, product_id, qty="2")
    before = _snapshot(session_factory, tenant_b)

    on_stock_updated(**_stock_event(tenant_a, product_id).as_message())
    rebuild_sale_day(**_sale_event(tenant_a, sale_id).as_message())

    assert _snapshot(session_factory, tenant_b) == before


def test_a_scheduled_task_of_a_writes_nothing_in_b(
    workers_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    tenant_a: Tenant,
    tenant_b: Tenant,
) -> None:
    """Les batchs par entreprise, lancés sur A seule.

    Ce sont les plus exposés : aucun événement ne les déclenche, donc aucun corps de
    message ne porte le `company_id`. Il vient d'un argument, et un argument se
    trompe plus facilement qu'un contrat.

    `rebuild_stock` n'en est pas : ce harnais écrit son journal de stock à la main,
    pour éprouver la RLS, et recalculer un CMP dessus n'aurait pas de sens — le
    `CHECK` de `product_stock` refuserait, pour une raison étrangère au sujet. Sa
    portée par entreprise est prouvée là où elle se prouve, sur un journal réel (T12).
    """
    before = _snapshot(session_factory, tenant_b)

    scan_due_debts(str(tenant_a.company_id), dt.date.today().isoformat())
    rebuild_recent_facts(str(tenant_a.company_id), 3)

    assert _snapshot(session_factory, tenant_b) == before


def test_a_task_routed_to_the_wrong_company_writes_nowhere(
    workers_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    tenant_a: Tenant,
    tenant_b: Tenant,
) -> None:
    """Un `company_id` erroné ne transporte aucune donnée d'un tenant à l'autre.

    C'est la panne qu'on redoute : une erreur de routage, un message rejoué avec le
    mauvais tenant. La tâche s'exécute alors **entièrement** chez B — contexte de B,
    RLS de B — et ne voit donc rien de A. Ce qu'elle écrit, elle le recalcule depuis
    les propres lignes de B : c'est une reconstruction inutile, pas une fuite.

    L'assertion porte donc sur la seule chose qui compte : rien de A n'apparaît chez
    B, et rien de A n'a bougé chez A. Exiger que B soit *inchangée* serait exiger que
    la RLS empêche B de relire ses propres ventes, ce qui n'a pas de sens.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = facts.extra_product(session, tenant_a, f"ROUTE-{uuid4().hex[:6]}")
        sale_id, _ = facts.sold_line(session, tenant_a, product_id, qty="2")
    before_a = _snapshot(session_factory, tenant_a)
    before_b = _snapshot(session_factory, tenant_b)

    # Le corps parle des objets de A, l'enveloppe porte le `company_id` de B.
    misrouted = _sale_event(tenant_a, sale_id)
    rebuild_sale_day(
        **Event(
            id=misrouted.id,
            company_id=tenant_b.company_id,
            event_type=misrouted.event_type,
            aggregate_type=misrouted.aggregate_type,
            aggregate_id=misrouted.aggregate_id,
            payload=misrouted.payload,
            occurred_at=misrouted.occurred_at,
        ).as_message()
    )

    # Les faits de A restent intacts : la tâche ne les a jamais vus.
    assert _snapshot(session_factory, tenant_a) == before_a

    after_b = _snapshot(session_factory, tenant_b)
    # Aucun produit de A n'a traversé, ni dans les faits, ni dans les alertes.
    assert not any(str(product_id) in row for row in after_b["daily_sales_facts"])
    assert after_b["notifications"] == before_b["notifications"]
    assert after_b["product_stock"] == before_b["product_stock"]


def test_the_company_enumeration_yields_identifiers_and_nothing_else(
    workers_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    tenant_a: Tenant,
    tenant_b: Tenant,
) -> None:
    """Le seul franchissement de la RLS des batchs, et il est borné aux identifiants.

    `companies` est en FORCE ROW LEVEL SECURITY : sans contexte, la table est vide
    même pour son propriétaire. Un batch nocturne doit pourtant passer sur toutes les
    entreprises. La fonction `SECURITY DEFINER` qui le permet ne rend donc **que**
    des `uuid` — ni nom, ni devise, ni fuseau. Rien à fuir.
    """
    identifiers = active_company_ids(session_factory)

    assert tenant_a.company_id in identifiers
    assert tenant_b.company_id in identifiers
    assert all(isinstance(value, UUID) for value in identifiers)
