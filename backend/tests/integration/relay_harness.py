"""Outils communs aux tests du relais et des consommateurs (T40).

Le relais est **inter-entreprises** par construction : `outbox_claim` ne filtre sur
aucun tenant. Un test qui compterait « les événements publiés » compterait donc aussi
ceux des autres suites. Les assertions portent par conséquent toujours sur des
identifiants d'événements créés par le test lui-même.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.events.inbox import Event
from app.core.events.outbox import emit
from app.core.events.types import EventType
from app.core.tenancy import TenantContext, tenant_transaction

_READ_STATE = text(
    """
    SELECT published_at, attempts
      FROM business_events
     WHERE company_id = :company_id AND id = :id
    """
)


class RecordingBus:
    """Bus de test : retient ce qu'on lui donne, ou échoue à volonté."""

    def __init__(self, *, fail_for: set[int] | None = None, fail_all: bool = False) -> None:
        self.published: list[Event] = []
        self.fail_for = fail_for or set()
        self.fail_all = fail_all

    def publish(self, event: Event) -> None:
        if self.fail_all or event.id in self.fail_for:
            # Ce que fait Redis injoignable, vu du relais : l'appel lève, et
            # l'événement ne doit surtout pas être marqué publié.
            raise RuntimeError("transport indisponible (simulé)")
        self.published.append(event)

    @property
    def published_ids(self) -> list[int]:
        return [event.id for event in self.published]


def write_event(
    session_factory: sessionmaker[Any],
    ctx: TenantContext,
    *,
    event_type: EventType = EventType.STOCK_UPDATED,
    aggregate_type: str = "product",
    payload: dict[str, Any] | None = None,
) -> tuple[int, UUID]:
    """Écrit un événement dans l'outbox et renvoie `(event_id, aggregate_id)`."""
    aggregate_id = uuid4()
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        event_id = emit(
            session,
            ctx,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload or {"qty_on_hand": "3.000", "below_reorder_point": False},
        )
    return event_id, aggregate_id


def read_state(session_factory: sessionmaker[Any], ctx: TenantContext, event_id: int) -> Any:
    """`(published_at, attempts)` d'un événement, lu sous RLS comme le fait l'API."""
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        return session.execute(_READ_STATE, {"company_id": ctx.company_id, "id": event_id}).one()


def bury_dead_letters(owner_engine: Engine) -> None:
    """Marque publiés les rebuts laissés par les tests : sans cela, `/system/workers`
    signalerait `outbox_dead_lettered` dans toutes les suites suivantes (ADR 0087)."""
    with owner_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE coges_bus"))
        connection.execute(
            text(
                "UPDATE business_events SET published_at = now() "
                "WHERE published_at IS NULL AND attempts >= 10"
            )
        )
