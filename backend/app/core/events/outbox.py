"""Outbox transactionnelle (décision 04).

L'événement est écrit **dans la transaction métier**, avec la donnée. Un relais le
publiera dans Redis **après COMMIT** (phase 08). Si la transaction est annulée,
l'événement disparaît avec elle : il n'existe pas d'événement sans fait.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from app.core import cache
from app.core.events.types import EventType
from app.core.tenancy import TenantContext

_INSERT_EVENT = text(
    """
    INSERT INTO business_events
        (company_id, event_type, aggregate_type, aggregate_id, payload)
    VALUES (:company_id, :event_type, :aggregate_type, :aggregate_id, CAST(:payload AS jsonb))
    RETURNING id
    """
)


def emit(
    session: Session,
    ctx: TenantContext,
    *,
    event_type: EventType,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
) -> int:
    """Écrit un événement dans l'outbox, dans la transaction courante.

    Ne publie rien : `published_at` reste NULL jusqu'au passage du relais.

    Chaque type d'événement vide aussi le tableau de bord côté worker
    (`app/workers/subscriptions.py`). L'API le fait elle-même, **après COMMIT**, pour
    que la lecture suivante voie l'écriture sans dépendre du relais (ADR 0061) ;
    le worker reste le filet.
    """
    if not isinstance(event_type, EventType):  # pragma: no cover - garde-fou de typage
        raise ValueError(f"Type d'événement hors liste : {event_type!r}")

    result = session.execute(
        _INSERT_EVENT,
        {
            "company_id": ctx.company_id,
            "event_type": event_type.value,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "payload": json.dumps(payload, ensure_ascii=False, default=str),
        },
    )
    cache.invalidate_after_commit(session, ctx.company_id, cache.DASHBOARD_KEY)
    return int(result.scalar_one())
