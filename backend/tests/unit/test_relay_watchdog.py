"""Le relais s'arrête de lui-même s'il ne finit pas un passage en 5 min (ADR 0077)."""

from __future__ import annotations

from typing import Any

from app.workers.relay import MAX_PASS_SECONDS, OutboxRelay, PassWatchdog, RelayPass


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_watchdog_exits_when_a_pass_lasts_too_long() -> None:
    clock = Clock()
    exits: list[int] = []
    watchdog = PassWatchdog(clock=clock, exit_process=exits.append)

    watchdog.pass_started()
    clock.now += MAX_PASS_SECONDS - 1
    assert watchdog.check() is True
    clock.now += 2
    assert watchdog.check() is False
    assert exits == [1]


def test_watchdog_ignores_the_wait_between_passes() -> None:
    """Dix minutes d'attente à vide ne sont pas un blocage."""
    clock = Clock()
    exits: list[int] = []
    watchdog = PassWatchdog(clock=clock, exit_process=exits.append)

    watchdog.pass_started()
    watchdog.pass_finished()
    clock.now += 3600
    assert watchdog.check() is True
    assert exits == []


def test_relay_marks_each_pass_for_the_watchdog() -> None:
    """La boucle encadre chaque passage, y compris celui qui lève."""
    events: list[str] = []

    class Recorder(PassWatchdog):
        def pass_started(self) -> None:
            events.append("start")

        def pass_finished(self) -> None:
            events.append("end")

    relay = OutboxRelay(bus=object(), session_factory=object(), watchdog=Recorder())  # type: ignore[arg-type]
    calls = iter([RuntimeError("base injoignable"), RelayPass(0, 0, 0, 0)])

    def run_once() -> RelayPass:
        outcome: Any = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        relay.stop()
        return outcome

    relay.run_once = run_once  # type: ignore[method-assign]
    relay._pause = lambda seconds: None  # type: ignore[method-assign]
    relay.run_forever()
    assert events == ["start", "end", "start", "end"]
