"""Interface du bus d'événements.

Cette interface existe depuis la phase 02 pour que les modules métier dépendent d'un
contrat stable et non d'une implémentation : remplacer le transport ne touche aucun
émetteur (décision 04). Le transport Redis est livré en phase 08, dans l'image
worker (`app/workers/bus.py`) — le noyau continue d'ignorer que Celery existe.

Elle prend un `Event` entier plutôt qu'une liste de champs : le relais lit l'outbox,
il a la ligne complète, et un paramètre oublié en route serait un champ perdu pour
tous les abonnés.
"""

from __future__ import annotations

from typing import Protocol

from app.core.events.inbox import Event


class TransportUnavailableError(Exception):
    """Le transport ne répond pas (broker injoignable, délai dépassé).

    Ce n'est pas un défaut de l'événement : le relais rend la tentative consommée et
    arrête son passage, au lieu de rapprocher des événements sains du rebut (ADR 0087).
    """


class EventBus(Protocol):
    """Contrat de publication, implémenté par le relais."""

    def publish(self, event: Event) -> None:
        """Publie un événement **déjà commité**.

        Au moins une fois : l'implémentation peut republier après un incident. C'est
        aux consommateurs d'être idempotents (`app.core.events.inbox.handle`).

        Lève `TransportUnavailableError` quand le transport lui-même est en panne ;
        toute autre exception est un échec propre à cet événement.
        """
        ...
