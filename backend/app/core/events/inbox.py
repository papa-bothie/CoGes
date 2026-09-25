"""Côté réception du bus : forme d'un événement publié, et idempotence.

Symétrique d'`outbox.py`. L'outbox garantit qu'un événement est publié **au moins
une fois** — un relais qui meurt entre la publication et le marquage republiera.
C'est donc ici que se joue « exactement une fois **en effet** » : la marque de
traitement est écrite dans la **transaction de l'effet**, de sorte que l'effet et sa
marque commitent ensemble. Jamais d'effet sans marque, jamais de marque sans effet
(ADR 0032).

Redis n'intervient pas dans cette garantie : une clé à TTL et l'écriture métier ne
peuvent pas commiter ensemble. C'est le même raisonnement que l'ADR 0027 pour les
clés d'idempotence des paiements.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.events.types import EventType
from app.core.tenancy import TenantContext, tenant_transaction

#: `ON CONFLICT DO NOTHING` puis `RETURNING` : une ligne signifie « premier passage »,
#: zéro ligne signifie « déjà traité ». C'est l'index unique qui tranche, pas un
#: `SELECT` préalable — sans quoi deux workers concurrents passeraient tous les deux.
_CLAIM = text(
    """
    INSERT INTO processed_events (company_id, consumer, event_id)
    VALUES (:company_id, :consumer, :event_id)
    ON CONFLICT (company_id, consumer, event_id) DO NOTHING
    RETURNING event_id
    """
)


@dataclass(frozen=True, slots=True)
class Event:
    """Un événement publié, tel qu'un consommateur le reçoit.

    Gelé : un consommateur ne réécrit pas ce qu'il a reçu. Le corps est
    auto-suffisant par contrat (`app/modules/sales/events.py`) — un abonné qui devrait
    relire la base pour comprendre son événement ne serait plus découplé de l'émetteur.
    """

    id: int
    company_id: UUID
    event_type: EventType
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    occurred_at: datetime

    def as_message(self) -> dict[str, Any]:
        """Forme JSON transportable par Celery : ni UUID, ni datetime, ni enum."""
        return {
            "event_id": self.id,
            "company_id": str(self.company_id),
            "event_type": self.event_type.value,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": str(self.aggregate_id),
            "payload": self.payload,
            "occurred_at": self.occurred_at.isoformat(),
        }

    @classmethod
    def from_message(
        cls,
        *,
        event_id: int,
        company_id: str,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        occurred_at: str,
    ) -> Event:
        """Reconstruit l'événement à l'entrée d'une tâche."""
        return cls(
            id=event_id,
            company_id=UUID(company_id),
            event_type=EventType(event_type),
            aggregate_type=aggregate_type,
            aggregate_id=UUID(aggregate_id),
            payload=payload,
            occurred_at=datetime.fromisoformat(occurred_at),
        )


def claim(session: Session, ctx: TenantContext, *, consumer: str, event_id: int) -> bool:
    """Réserve l'événement pour ce consommateur. `False` s'il a déjà été traité."""
    row = session.execute(
        _CLAIM,
        {"company_id": ctx.company_id, "consumer": consumer, "event_id": event_id},
    ).one_or_none()
    return row is not None


#: Un gestionnaire d'événement : il reçoit la session de la transaction en cours, le
#: contexte tenant déjà posé, et l'événement. Il ne commit pas lui-même.
Handler = Callable[[Session, TenantContext, Event], None]


def handle(
    event: Event,
    *,
    consumer: str,
    handler: Handler,
    session_factory: sessionmaker[Any] | None = None,
) -> bool:
    """Exécute `handler` une seule fois pour cet événement. `False` si c'est un rejeu.

    Le contexte tenant vient de `company_id` de l'événement, posé par la voie unique
    du projet (`tenant_transaction`) : une tâche d'une entreprise ne peut rien écrire
    chez une autre, même en cas d'erreur de routage — la RLS refuserait.
    """
    ctx = TenantContext.bootstrap(event.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        if not claim(session, ctx, consumer=consumer, event_id=event.id):
            return False
        handler(session, ctx, event)
    return True
