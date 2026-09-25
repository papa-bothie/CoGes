"""Publié au moins une fois, appliqué une seule fois **en effet**.

L'outbox ne promet pas mieux qu'une publication *au moins* une fois : un relais tué
entre la publication et le marquage republiera, et `task_acks_late` rend à la file
toute tâche dont le worker meurt. Le rejeu n'est donc pas un incident rare, c'est le
régime nominal — ce qui déplace toute la garantie du côté du **consommateur**.

Elle tient à une seule chose : la marque `processed_events` est écrite dans la
transaction de l'effet. Jamais d'effet sans marque, jamais de marque sans effet. Ce
sont ces deux moitiés que ces tests séparent :

* rejouer le même événement ne produit pas un second effet ;
* un effet qui échoue n'a pas laissé de marque derrière lui, donc le rejeu marchera ;
* deux consommateurs différents d'un même événement s'exécutent tous les deux.

Redis ne peut pas porter cette garantie : une clé à TTL et une écriture métier ne
commitent pas ensemble. C'est le raisonnement de l'ADR 0027 pour les paiements, repris
ici pour le bus (ADR 0032).
"""

from __future__ import annotations

import datetime as dt
import itertools
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.events.inbox import Event, claim, handle
from app.core.events.types import EventType
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.inventory.events import stock_updated_payload
from app.modules.sales.events import AGGREGATE_TYPE as SALE_AGGREGATE
from app.workers.tasks.analytics import CONSUMER as FACTS_CONSUMER
from app.workers.tasks.analytics import rebuild_sale_day
from app.workers.tasks.notifications import STOCK_CONSUMER, on_stock_updated
from tests.conftest import DemoCompany
from tests.integration import facts_harness as facts
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: Identifiants synthétiques : `processed_events` ne porte aucune clé étrangère vers
#: `business_events` (révision 0010), et une marque orpheline est inoffensive.
_ids = itertools.count(920_000_000)

_COUNT_NOTIFICATIONS = text(
    """
    SELECT count(*) FROM notifications
     WHERE company_id = :company_id AND data->>'entity_id' = :entity_id
    """
)

_COUNT_MARKS = text(
    """
    SELECT count(*) FROM processed_events
     WHERE company_id = :company_id AND consumer = :consumer AND event_id = :event_id
    """
)


def _stock_event(tenant: Tenant, product_id: UUID, *, qty: str) -> Event:
    return Event(
        id=next(_ids),
        company_id=tenant.company_id,
        event_type=EventType.STOCK_UPDATED,
        aggregate_type="product",
        aggregate_id=product_id,
        payload=stock_updated_payload(
            product_id=product_id,
            qty_on_hand=Decimal(qty),
            avg_cost=Decimal("600.0000"),
            movement_id=uuid4(),
            below_reorder_point=True,
        ),
        occurred_at=dt.datetime.now(dt.UTC),
    )


def _sale_event(tenant: Tenant, sale_id: UUID, sold_at: dt.datetime) -> Event:
    return Event(
        id=next(_ids),
        company_id=tenant.company_id,
        event_type=EventType.SALE_CONFIRMED,
        aggregate_type=SALE_AGGREGATE,
        aggregate_id=sale_id,
        payload={"sale_no": "V-000001", "sold_at": sold_at.isoformat(), "total": "1000.00"},
        occurred_at=dt.datetime.now(dt.UTC),
    )


def _count(session_factory: sessionmaker[Any], company_id: UUID, sql: Any, params: Any) -> int:
    """Compte à travers la RLS, avec le contexte du tenant : comme l'API le ferait."""
    with tenant_transaction(
        TenantContext.bootstrap(company_id), session_factory=session_factory
    ) as session:
        return int(session.execute(sql, params).scalar_one())


def _scalar(session_factory: sessionmaker[Any], tenant: Tenant, sql: Any, params: Any) -> int:
    return _count(session_factory, tenant.company_id, sql, params)


def _demo_product(client: TestClient, token: str) -> UUID:
    """Un produit de l'entreprise de démonstration, créé par la route réelle."""
    marker = uuid4().hex[:8]
    response = client.post(
        "/api/v1/products",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "sku": f"IDEM-{marker}",
            "name": f"Rejoué {marker}",
            "unit_price": "1000.00",
            "default_tax_rate": "0",
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


# ---------------------------------------------------- un seul effet par événement


def test_replaying_a_stock_event_writes_a_single_alert(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Le même événement traité deux fois ⇒ une alerte, et la seconde passe le dit.

    Le second passage ne se contente pas de ne rien écrire : il **annonce** qu'il
    s'agit d'un rejeu. Un consommateur qui renverrait « traité » dans les deux cas
    rendrait la panne indétectable le jour où la marque cesserait d'être posée.

    L'entreprise de démonstration, et non un tenant du harnais de fuite : l'alerte
    n'existe que s'il y a quelqu'un à alerter, et le destinataire se déduit d'un droit.
    Un tenant sans rôle attribué produirait « zéro alerte » pour une raison qui n'a
    rien à voir avec l'idempotence.
    """
    product_id = _demo_product(api_client, alpha_token)
    event = Event(
        id=next(_ids),
        company_id=company_alpha.company_id,
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
    params = {"company_id": company_alpha.company_id, "entity_id": str(product_id)}

    first = on_stock_updated(**event.as_message())
    second = on_stock_updated(**event.as_message())

    assert (first, second) == ("handled", "already-processed")
    assert _count(session_factory, company_alpha.company_id, _COUNT_NOTIFICATIONS, params) == 1


def test_replaying_a_sale_event_rebuilds_the_same_day_once(
    workers_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    """Rejouer la reconstruction ne décale aucun chiffre.

    Deux garanties se superposent ici, et il faut les deux. La marque évite le second
    passage ; et même si elle manquait, la requête du § 6.1 est idempotente — c'est
    T30. La ceinture et les bretelles, parce qu'un agrégat faux ne se voit pas.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = facts.extra_product(session, tenant_a, f"IDEM-{uuid4().hex[:6]}")
        sale_id, _ = facts.sold_line(session, tenant_a, product_id, qty="3")

    day = facts.today_in_company(session_factory, tenant_a.company_id)
    event = _sale_event(tenant_a, sale_id, dt.datetime.now(dt.UTC))

    assert rebuild_sale_day(**event.as_message()) == "rebuilt"
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        once = facts.read_fact(session, tenant_a, day, product_id)

    assert rebuild_sale_day(**event.as_message()) == "already-processed"
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        twice = facts.read_fact(session, tenant_a, day, product_id)

    assert once is not None
    assert tuple(twice) == tuple(once)


def test_two_consumers_of_the_same_event_both_run(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """La marque porte sur (consommateur, événement), jamais sur l'événement seul.

    `stock.updated` a deux abonnés : l'alerte et l'invalidation du cache. Une marque
    qui ne nommerait pas son consommateur ferait taire le second — le premier arrivé
    déciderait pour tout le monde, et lequel arrive en premier n'est pas une propriété
    du système.
    """
    event = _stock_event(tenant_a, tenant_a.product_id, qty="0.000")

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        first = claim(session, tenant_a.ctx, consumer="consommateur.un", event_id=event.id)
        second = claim(session, tenant_a.ctx, consumer="consommateur.deux", event_id=event.id)
        replayed = claim(session, tenant_a.ctx, consumer="consommateur.un", event_id=event.id)

    assert (first, second, replayed) == (True, True, False)


# ------------------------------------------------ jamais de marque sans effet


def test_a_failing_handler_leaves_no_mark_behind(
    workers_bound_to_test_database: None, session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """L'effet échoue ⇒ la marque part avec lui, et le rejeu peut réussir.

    C'est l'autre moitié de la garantie, celle qu'on oublie : une marque posée hors de
    la transaction de l'effet transformerait la première panne venue en perte
    silencieuse de l'événement. Ici, le ROLLBACK emporte les deux ensemble.
    """
    event = _stock_event(tenant_a, tenant_a.product_id, qty="0.000")
    marks = {
        "company_id": tenant_a.company_id,
        "consumer": STOCK_CONSUMER,
        "event_id": event.id,
    }

    def _explode(*_: Any) -> None:
        raise RuntimeError("effet en échec (simulé)")

    with pytest.raises(RuntimeError):
        handle(event, consumer=STOCK_CONSUMER, handler=_explode)

    assert _scalar(session_factory, tenant_a, _COUNT_MARKS, marks) == 0

    # Et la preuve que la marque manquante sert à quelque chose : le rejeu passe.
    assert handle(event, consumer=STOCK_CONSUMER, handler=lambda *_: None) is True
    assert _scalar(session_factory, tenant_a, _COUNT_MARKS, marks) == 1


def test_a_mark_belongs_to_one_company_only(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Deux entreprises peuvent porter le même `event_id` sans se gêner.

    `business_events.id` est une séquence globale, donc la collision n'arrive pas en
    production — mais la clé primaire de `processed_events` commence tout de même par
    `company_id`. Sans cela, l'événement d'une entreprise pourrait marquer comme
    traité celui d'une autre, et l'autre ne s'en apercevrait jamais.
    """
    shared_id = next(_ids)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        for_a = claim(session, tenant_a.ctx, consumer=FACTS_CONSUMER, event_id=shared_id)
    with tenant_transaction(tenant_b.ctx, session_factory=session_factory) as session:
        for_b = claim(session, tenant_b.ctx, consumer=FACTS_CONSUMER, event_id=shared_id)

    assert (for_a, for_b) == (True, True)
