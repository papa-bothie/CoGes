"""Panne de Redis : aucun événement sain ne finit au rebut (prompt 21, P1.1 ; ADR 0087).

`outbox_claim` consomme une tentative à chaque réclamation et cesse de réclamer à 10.
Une panne de transport n'est pas un défaut de l'événement : si chaque passage pendant
la panne coûtait une tentative, quelques minutes sans Redis suffiraient à mettre au
rebut des événements sains, qui ne repartiraient plus jamais seuls.
"""

from __future__ import annotations

from typing import Any

import pytest
from kombu.exceptions import OperationalError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.events.bus import TransportUnavailableError
from app.core.events.inbox import Event
from app.workers.bus import CeleryEventBus
from app.workers.relay import OutboxRelay
from tests.integration.relay_harness import (
    RecordingBus,
    bury_dead_letters,
    read_state,
    write_event,
)
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

BATCH = 500
#: Plus que le plafond de tentatives : la panne dure.
OUTAGE_PASSES = 12


class RedisDownBus:
    """Un bus dont le transport est tombé : il le dit par `TransportUnavailableError`."""

    def __init__(self) -> None:
        self.calls = 0

    def publish(self, event: Event) -> None:
        self.calls += 1
        raise TransportUnavailableError("Connection refused")


class _BrokenCelery:
    """Ce que lève Celery quand le broker ne répond pas : une `OperationalError` de kombu."""

    def send_task(self, *args: Any, **kwargs: Any) -> None:
        raise OperationalError("Error 111 connecting to redis:6379. Connection refused.")


def _relay(factory: sessionmaker[Any], bus: Any) -> OutboxRelay:
    return OutboxRelay(bus, session_factory=factory, batch_size=BATCH, poll_interval=0.0)


@pytest.fixture(autouse=True)
def _empty_outbox(relay_session_factory: sessionmaker[Any]) -> None:
    while not _relay(relay_session_factory, RecordingBus()).run_once().idle:
        pass


def test_events_survive_a_redis_outage_longer_than_the_attempt_cap(
    session_factory: sessionmaker[Any],
    relay_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    event_id, _ = write_event(session_factory, tenant_a.ctx)

    down = RedisDownBus()
    for _ in range(OUTAGE_PASSES):
        result = _relay(relay_session_factory, down).run_once()
        assert result.dead_lettered == 0, "une panne de transport a mis un événement au rebut"

    state = read_state(session_factory, tenant_a.ctx, event_id)
    assert state.published_at is None
    assert state.attempts == 0, "la panne de transport a consommé des tentatives"

    working = RecordingBus()
    _relay(relay_session_factory, working).run_once()
    assert event_id in working.published_ids, "l'événement n'est pas reparti au retour de Redis"
    assert read_state(session_factory, tenant_a.ctx, event_id).published_at is not None


def test_a_transport_failure_stops_the_pass_and_releases_the_whole_batch(
    session_factory: sessionmaker[Any],
    relay_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    """Redis tombé, inutile d'essayer les 99 événements suivants : le passage s'arrête."""
    first, _ = write_event(session_factory, tenant_a.ctx)
    second, _ = write_event(session_factory, tenant_a.ctx)

    down = RedisDownBus()
    result = _relay(relay_session_factory, down).run_once()

    assert down.calls == 1
    assert result.failed >= 1
    for event_id in (first, second):
        assert read_state(session_factory, tenant_a.ctx, event_id).attempts == 0


def test_the_celery_bus_reports_a_broker_failure_as_a_transport_failure(
    session_factory: sessionmaker[Any],
    relay_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    """Le vrai bus, broker injoignable : la tentative est rendue, comme avec le bus simulé."""
    event_id, _ = write_event(session_factory, tenant_a.ctx)
    bus = CeleryEventBus(_BrokenCelery())  # type: ignore[arg-type]

    _relay(relay_session_factory, bus).run_once()

    assert read_state(session_factory, tenant_a.ctx, event_id).attempts == 0


def test_a_poisoned_event_still_reaches_the_dead_letter(
    session_factory: sessionmaker[Any],
    relay_session_factory: sessionmaker[Any],
    owner_engine: Engine,
    tenant_a: Tenant,
) -> None:
    """Un échec propre à l'événement compte toujours : le plafond de 10 tient."""
    event_id, _ = write_event(session_factory, tenant_a.ctx)
    poisoned = RecordingBus(fail_for={event_id})

    try:
        dead = 0
        for _ in range(OUTAGE_PASSES):
            dead += _relay(relay_session_factory, poisoned).run_once().dead_lettered

        assert dead == 1
        state = read_state(session_factory, tenant_a.ctx, event_id)
        assert state.published_at is None
        assert state.attempts == 10
    finally:
        bury_dead_letters(owner_engine)
