"""Le calendrier des relances, en fonctions pures (ADR 0133)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.core import renewal

DAKAR = renewal.zone("Africa/Dakar")
END = datetime(2026, 12, 10, 14, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("offset", "stage"),
    [(-7, None), (-3, None), (-2, None), (-1, "eve"), (0, "due"), (1, "due"), (2, "last")]
    + [(3, "suspended"), (4, "suspended"), (40, "suspended")],
)
def test_the_calendar_has_no_seven_or_three_days_warning(offset: int, stage: str | None) -> None:
    assert renewal.calendar_stage(offset) == stage


def _walk(start: int, stop: int, *, skip: frozenset[int] = frozenset()) -> list[tuple[int, str]]:
    """Fait tourner la tâche une fois par jour (sauf les jours `skip`) de `start` à `stop`."""
    done: str | None = None
    done_on: date | None = None
    seen: list[tuple[int, str]] = []
    base = date(2026, 12, 10)
    for offset in range(start, stop + 1):
        if offset in skip:
            continue
        today = base + timedelta(days=offset)
        for _ in range(2):  # relancée le même jour : rien de plus
            stage = renewal.next_stage(offset=offset, done=done, done_on=done_on, today=today)
            if stage is not None:
                seen.append((offset, stage))
                done, done_on = stage, today
    return seen


def test_day_by_day_exactly_eve_due_last_then_pause_at_j_plus_3() -> None:
    assert _walk(-8, 6) == [(-1, "eve"), (0, "due"), (2, "last"), (3, "suspended")]


def test_a_missed_eve_gives_the_due_reminder_only() -> None:
    assert _walk(0, 4, skip=frozenset()) == [(0, "due"), (2, "last"), (3, "suspended")]


def test_a_missed_j_day_is_caught_up_the_next_day() -> None:
    assert _walk(-1, 4, skip=frozenset({0})) == [
        (-1, "eve"),
        (1, "due"),
        (2, "last"),
        (3, "suspended"),
    ]


def test_never_a_pause_without_a_last_reminder_the_day_before() -> None:
    # La tâche n'a pas tourné de J-1 à J+4 : dernier rappel à J+5, pause à J+6.
    assert _walk(-1, 7, skip=frozenset(range(-1, 5))) == [(5, "last"), (6, "suspended")]


def test_an_expired_period_found_late_gets_the_last_reminder_first() -> None:
    assert _walk(40, 41) == [(40, "last"), (41, "suspended")]


def test_the_days_are_counted_in_the_company_time_zone() -> None:
    # Échéance le 10/12 à 23 h 30 à Dakar (UTC) = le 11/12 à 00 h 30 à Douala (UTC+1).
    ends = datetime(2026, 12, 10, 23, 30, tzinfo=UTC)
    now = datetime(2026, 12, 10, 6, 30, tzinfo=UTC)
    assert renewal.offset_days(ends, now, DAKAR) == 0
    assert renewal.offset_days(ends, now, renewal.zone("Africa/Douala")) == -1


def test_an_unknown_zone_counts_in_utc() -> None:
    assert renewal.zone("Pas/Un_Fuseau").key == "UTC"


@pytest.mark.parametrize(
    ("status", "trial", "period", "license", "kind"),
    [
        ("trial", END, None, False, "trial"),
        ("past_due", END, None, False, "trial"),
        ("active", END, END, False, "paid"),
        ("past_due", END, END, False, "paid"),
        ("active", END, None, False, None),  # Premium sans échéance
        ("active", None, None, True, None),  # licence sur site
        ("active", None, END, True, None),
        ("suspended", END, END, False, None),
    ],
)
def test_which_deadline_is_followed(
    status: str,
    trial: datetime | None,
    period: datetime | None,
    license: bool,
    kind: str | None,
) -> None:
    found = renewal.deadline(
        status=status, trial_ends_at=trial, current_period_end=period, is_license=license
    )
    assert (found.kind if found else None) == kind


def _banner(now: datetime) -> renewal.Banner | None:
    return renewal.banner(
        status="trial",
        trial_ends_at=END,
        current_period_end=None,
        is_license=False,
        now=now,
        timezone="Africa/Dakar",
    )


def test_the_banner_shows_from_the_eve_to_j_plus_2() -> None:
    shown = [
        (offset, b.stage, b.days_left)
        for offset in range(-3, 5)
        if (b := _banner(END + timedelta(days=offset))) is not None
    ]
    assert shown == [
        (-1, "eve", 4),
        (0, "due", 3),
        (1, "due", 2),
        (2, "last", 1),
        (3, "last", 1),  # pas encore mise en pause : le dernier rappel reste
        (4, "last", 1),
    ]
    found = _banner(END)
    assert found is not None
    assert found.pause_on == date(2026, 12, 13)
