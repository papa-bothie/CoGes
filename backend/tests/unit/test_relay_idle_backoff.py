"""Espacement du relais quand l'outbox est vide (ADR 0040).

Sur l'offre gratuite de Neon, un sondage par seconde empêcherait la base de
s'endormir. Le relais double donc son attente à chaque passage vide, jusqu'au
plafond, et revient à l'intervalle de sondage dès qu'un événement passe.
"""

from __future__ import annotations

from typing import Any

from app.workers.relay import OutboxRelay, RelayPass

IDLE = RelayPass(claimed=0, published=0, failed=0, dead_lettered=0)
BUSY = RelayPass(claimed=3, published=3, failed=0, dead_lettered=0)
FAILED = RelayPass(claimed=2, published=0, failed=2, dead_lettered=0)


class _RecordingRelay(OutboxRelay):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(bus=None, session_factory=object(), **kwargs)  # type: ignore[arg-type]
        self.pauses: list[float] = []

    def _pause(self, seconds: float) -> None:
        self.pauses.append(seconds)


def test_idle_passes_double_the_wait_up_to_the_ceiling() -> None:
    relay = _RecordingRelay(poll_interval=1.0, idle_max=600.0)
    for _ in range(12):
        relay._sleep_after(IDLE)
    assert relay.pauses == [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 600, 600]


def test_an_event_brings_the_wait_back_to_the_poll_interval() -> None:
    relay = _RecordingRelay(poll_interval=1.0, idle_max=600.0)
    for _ in range(5):
        relay._sleep_after(IDLE)
    relay._sleep_after(BUSY)
    relay._sleep_after(IDLE)
    # Un passage actif enchaîne sans pause ; la file vide suivante repart de 1 s.
    assert relay.pauses == [1, 2, 4, 8, 16, 1]


def test_default_ceiling_keeps_the_historical_one_second_poll() -> None:
    relay = _RecordingRelay(poll_interval=1.0, idle_max=1.0)
    for _ in range(4):
        relay._sleep_after(IDLE)
    assert relay.pauses == [1, 1, 1, 1]


def test_publication_failure_uses_the_error_backoff_not_the_idle_wait() -> None:
    relay = _RecordingRelay(poll_interval=1.0, idle_max=600.0, backoff_max=60.0)
    relay._sleep_after(FAILED)
    relay._sleep_after(FAILED)
    relay._sleep_after(IDLE)
    assert relay.pauses == [1, 2, 1]


def test_stop_interrupts_a_long_idle_wait() -> None:
    relay = OutboxRelay(bus=None, session_factory=object(), poll_interval=1.0, idle_max=600.0)  # type: ignore[arg-type]
    relay.stop()
    # Sans le réveil, cette attente durerait une seconde ; `stop()` l'a déjà levée.
    relay._pause(600)
