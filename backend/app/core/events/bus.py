"""Interface du bus d'événements.

Le transport (Redis) et le relais sont livrés en **phase 08**. Cette interface
existe dès maintenant pour que les modules métier dépendent d'un contrat stable et
non d'une implémentation : remplacer le transport ne touchera aucun émetteur
(décision 04).
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.core.events.types import EventType


class EventBus(Protocol):
    """Contrat de publication, implémenté par le relais en phase 08."""

    def publish(
        self,
        *,
        event_id: int,
        company_id: UUID,
        event_type: EventType,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
    ) -> None:
        """Publie un événement déjà commité. Doit être idempotent côté consommateur."""
        ...
