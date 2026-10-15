"""Relais de l'outbox — le seul composant multi-tenant du projet.

    python -m app.workers.relay

Il lit `business_events` sans distinction d'entreprise et publie chaque événement
dans Redis. Il n'a pourtant ni `BYPASSRLS`, ni le moindre privilège de table : il
appelle deux fonctions `SECURITY DEFINER` appartenant à `coges_bus` (ADR 0032), sur
le patron d'`auth_lookup` (ADR 0005). C'est la seule surface qui franchit la RLS, et
elle tient en deux appels.

Le protocole en trois temps, et pourquoi il est dans cet ordre :

1. `outbox_claim` verrouille un lot en `FOR UPDATE SKIP LOCKED`, consomme une
   tentative et **commite** ;
2. les événements partent vers Celery ;
3. `outbox_mark_published` horodate ceux qui sont réellement partis.

Une interruption entre 1 et 3 laisse `published_at IS NULL` : l'événement est
réclamé de nouveau au redémarrage. C'est **au moins une fois**, et c'est le test
**T40**. L'inverse — marquer avant de publier — serait « au plus une fois », donc une
perte silencieuse, ce que la décision 04 refuse.

Le relais ne consomme rien et n'appelle jamais l'API (Diagramme 2, `B⇸A`) : il écrit
en base et enfile des tâches, point.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import FrameType
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.database import get_relay_session_factory
from app.core.events.inbox import Event
from app.core.events.types import EventType
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

#: Les deux seuls appels autorisés à voir toutes les entreprises. Le SQL vit ici et
#: nulle part ailleurs : un test d'architecture le vérifie.
_CLAIM = text(
    """
    SELECT id, company_id, event_type, aggregate_type, aggregate_id,
           payload, occurred_at, attempts
      FROM outbox_claim(:batch)
    """
)
_MARK_PUBLISHED = text("SELECT outbox_mark_published(:ids) AS marked")


@dataclass(frozen=True, slots=True)
class ClaimedEvent:
    """Un événement réclamé, et le compte de tentatives que le claim vient de consommer.

    `attempts` ne voyage pas dans `Event` : c'est une affaire de relais, pas une
    information que le corps de l'événement doit porter jusqu'aux abonnés.
    """

    event: Event
    attempts: int


@dataclass(frozen=True, slots=True)
class RelayPass:
    """Bilan d'un passage, pour les journaux et les tests."""

    claimed: int
    published: int
    failed: int
    dead_lettered: int

    @property
    def idle(self) -> bool:
        return self.claimed == 0


#: Durée maximale d'un passage. Au-delà, le relais est bloqué (base qui ne répond plus,
#: verrou, Redis suspendu) : il s'arrête de lui-même et Docker le relance (ADR 0077).
MAX_PASS_SECONDS = 300.0


class PassWatchdog:
    """Fil qui arrête le processus si un passage dure plus de `MAX_PASS_SECONDS`.

    Un relais bloqué continuerait de battre (le battement vit dans son propre fil) :
    c'est ce chien de garde qui transforme le blocage en arrêt, que `restart` et
    `autoheal` savent réparer. `os._exit` et non `sys.exit` : le fil principal est
    justement celui qui ne rend plus la main.
    """

    def __init__(
        self,
        *,
        limit: float = MAX_PASS_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        exit_process: Callable[[int], None] = os._exit,
        check_every: float = 10.0,
    ) -> None:
        self._limit = limit
        self._clock = clock
        self._exit = exit_process
        self._check_every = check_every
        self._started_at: float | None = None
        self._stop = threading.Event()

    def pass_started(self) -> None:
        self._started_at = self._clock()

    def pass_finished(self) -> None:
        self._started_at = None

    def check(self) -> bool:
        """Rend `False` (et arrête le processus) si le passage en cours a trop duré."""
        started = self._started_at
        if started is None or self._clock() - started <= self._limit:
            return True
        logger.critical(
            "Passage du relais bloqué : arrêt du processus",
            extra={"limit_seconds": self._limit},
        )
        # `os._exit` coupe tout, y compris le fil d'envoi de Sentry : on le vide d'abord.
        import sentry_sdk  # noqa: PLC0415

        sentry_sdk.flush(timeout=2)
        self._exit(1)
        return False

    def _run(self) -> None:
        while not self._stop.wait(self._check_every):
            self.check()

    def start(self) -> PassWatchdog:
        threading.Thread(target=self._run, name="relay-watchdog", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()


class OutboxRelay:
    """Boucle de publication. Une instance par processus."""

    def __init__(
        self,
        bus: Any,
        *,
        session_factory: sessionmaker[Any] | None = None,
        batch_size: int | None = None,
        poll_interval: float | None = None,
        max_attempts: int | None = None,
        backoff_max: float | None = None,
        idle_max: float | None = None,
        watchdog: PassWatchdog | None = None,
    ) -> None:
        settings = get_settings()
        self._watchdog = watchdog
        self._bus = bus
        self._session_factory = session_factory or get_relay_session_factory()
        self._batch_size = batch_size or settings.outbox_batch_size
        self._poll_interval = (
            settings.outbox_poll_interval_seconds if poll_interval is None else poll_interval
        )
        self._max_attempts = max_attempts or settings.outbox_max_attempts
        self._backoff_max = backoff_max or settings.outbox_backoff_max_seconds
        # Plafond de l'espacement quand la file reste vide (ADR 0040). Égal à
        # `poll_interval` par défaut : aucun espacement, le comportement historique.
        # En préproduction sur l'offre gratuite de Neon, il monte à 600 s pour que la
        # base puisse s'endormir entre deux passages.
        idle_ceiling = settings.outbox_idle_max_seconds if idle_max is None else idle_max
        self._idle_max = max(idle_ceiling, self._poll_interval)
        self._backoff = 0.0
        self._idle_wait = 0.0
        self._stopping = False
        # Réveillé par `stop()` : une attente de dix minutes ne retarde pas l'arrêt
        # du conteneur.
        self._wake = threading.Event()

    # ------------------------------------------------------------------ un passage

    def _claim(self) -> list[ClaimedEvent]:
        """Réclame un lot et commite immédiatement la consommation de tentative.

        La transaction est courte par construction : garder le verrou pendant la
        publication bloquerait un second relais et, en cas de panne de Redis,
        immobiliserait le lot jusqu'au délai d'expiration.
        """
        session: Session = self._session_factory()
        try:
            with session.begin():
                rows = session.execute(_CLAIM, {"batch": self._batch_size}).all()
            return [
                ClaimedEvent(
                    event=Event(
                        id=row.id,
                        company_id=row.company_id,
                        event_type=EventType(row.event_type),
                        aggregate_type=row.aggregate_type,
                        aggregate_id=row.aggregate_id,
                        payload=row.payload,
                        occurred_at=row.occurred_at,
                    ),
                    attempts=int(row.attempts),
                )
                for row in rows
            ]
        finally:
            session.close()

    def _mark_published(self, event_ids: list[int]) -> int:
        session: Session = self._session_factory()
        try:
            with session.begin():
                marked = session.execute(_MARK_PUBLISHED, {"ids": event_ids}).scalar_one()
            return int(marked)
        finally:
            session.close()

    def run_once(self) -> RelayPass:
        """Un lot : réclamer, publier, marquer. Ne lève pas sur un échec de publication."""
        claimed = self._claim()
        if not claimed:
            return RelayPass(claimed=0, published=0, failed=0, dead_lettered=0)

        published: list[int] = []
        failed = 0
        dead_lettered = 0
        for item in claimed:
            try:
                self._bus.publish(item.event)
            except Exception:
                failed += 1
                # `attempts` a déjà été incrémenté par `outbox_claim` : l'événement
                # qui atteint le plafond ne sera plus réclamé. Il reste en base,
                # rejouable à la main après correction — aucune donnée ne part vers
                # un support jetable (ADR 0032).
                exhausted = item.attempts >= self._max_attempts
                if exhausted:
                    dead_lettered += 1
                logger.error(
                    "Publication impossible",
                    extra={
                        "event_id": item.event.id,
                        "event_type": item.event.event_type.value,
                        "attempts": item.attempts,
                        "dead_lettered": exhausted,
                    },
                    exc_info=True,
                )
            else:
                published.append(item.event.id)

        marked = self._mark_published(published) if published else 0
        result = RelayPass(
            claimed=len(claimed), published=marked, failed=failed, dead_lettered=dead_lettered
        )
        logger.info(
            "Passage du relais",
            extra={
                "claimed": result.claimed,
                "published": result.published,
                "failed": result.failed,
                "dead_lettered": result.dead_lettered,
            },
        )
        return result

    # -------------------------------------------------------------------- la boucle

    def _pause(self, seconds: float) -> None:
        """Attend, sauf si l'arrêt est demandé entre-temps."""
        self._wake.wait(seconds)

    def _next_idle_wait(self) -> float:
        """Attente après un passage vide : double à chaque passage vide, jusqu'au plafond.

        La première attente vaut `poll_interval` ; la file qui reste vide espace ses
        sondages, ce qui laisse une base serverless s'endormir (ADR 0040).
        """
        self._idle_wait = min(max(self._idle_wait * 2, self._poll_interval), self._idle_max)
        return self._idle_wait

    def _sleep_after(self, result: RelayPass) -> None:
        """Pause quand la file est vide, back-off exponentiel quand la publication échoue.

        Le back-off protège Redis d'une tempête de reprises ; il ne retarde jamais un
        lot qui passe, puisqu'un passage réussi le remet à zéro. De même, un passage
        qui trouve un événement ramène l'attente à vide à `poll_interval`.
        """
        if result.failed:
            self._backoff = min(max(self._backoff * 2, self._poll_interval), self._backoff_max)
            self._pause(self._backoff)
            return
        self._backoff = 0.0
        if result.idle:
            self._pause(self._next_idle_wait())
        else:
            self._idle_wait = 0.0

    def stop(self, *_: object) -> None:
        """Demande l'arrêt à la fin du lot en cours, sans couper une publication."""
        self._stopping = True
        self._wake.set()
        logger.info("Arrêt du relais demandé")

    def run_forever(self) -> None:
        while not self._stopping:
            if self._watchdog is not None:
                self._watchdog.pass_started()
            try:
                result: RelayPass | None = self.run_once()
            except Exception:
                # Base injoignable, fonction absente, lot illisible : on journalise et
                # on réessaie. Un relais qui s'arrête est une file qui ne part plus.
                logger.error("Passage du relais en échec", exc_info=True)
                result = None
            finally:
                if self._watchdog is not None:
                    self._watchdog.pass_finished()
            if result is None:
                self._backoff = min(max(self._backoff * 2, self._poll_interval), self._backoff_max)
                self._pause(self._backoff)
                continue
            self._sleep_after(result)


def main() -> None:
    """Point d'entrée du conteneur `relay`."""
    configure_logging()
    from app.core.observability import init_sentry  # noqa: PLC0415

    init_sentry("relay")
    from app.core.role_guard import assert_runtime_role  # noqa: PLC0415
    from app.workers.bus import CeleryEventBus  # noqa: PLC0415
    from app.workers.celery_app import celery_app  # noqa: PLC0415

    relay_factory = get_relay_session_factory()
    # Garde-fou 1 de l'ADR 0042 : refuse de démarrer sous coges_owner ou BYPASSRLS.
    assert_runtime_role(relay_factory.kw["bind"])
    from app.core.heartbeat import Heartbeat  # noqa: PLC0415

    # Le battement vit dans son propre fil : il continue pendant les attentes de dix
    # minutes de la préproduction, sans réveiller la base (ADR 0040, 0077).
    Heartbeat("relay").start()
    relay = OutboxRelay(
        CeleryEventBus(celery_app),
        session_factory=relay_factory,
        watchdog=PassWatchdog().start(),
    )
    for received in (signal.SIGINT, signal.SIGTERM):
        signal.signal(received, _handler(relay))
    logger.info("Relais de l'outbox démarré")
    relay.run_forever()


def _handler(relay: OutboxRelay) -> Any:
    def _stop(signum: int, frame: FrameType | None) -> None:
        relay.stop()

    return _stop


if __name__ == "__main__":
    main()
