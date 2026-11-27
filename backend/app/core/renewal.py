"""Le calendrier des relances : fin d'essai et échéance d'une période payée (ADR 0133).

Fonctions pures, partagées par la tâche de nuit (`modules/platform`) et par le bandeau de
l'application (`modules/companies`, à partir de `current_plan()`) : les deux comptent les
jours de la même façon, dans le fuseau de l'entreprise.

Soit E l'échéance (`current_period_end` pour une période payée, sinon `trial_ends_at`),
et J son jour calendaire dans le fuseau de l'entreprise :

- J-1 : rappel « veille » (`eve`) ;
- J et J+1 : rappel « jour J » (`due`), l'abonnement passe en `past_due`, l'accès reste ;
- J+2 : dernier rappel (`last`), qui annonce la pause du lendemain ;
- J+3 et après : suspension (`suspended`).

Une étape au plus par jour, jamais en arrière, et jamais de suspension sans un dernier
rappel donné un jour précédent (choix du propriétaire) : une nuit manquée retarde la
pause, elle ne la précipite pas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Stage = Literal["eve", "due", "last", "suspended"]
Kind = Literal["trial", "paid"]

#: Jours d'accès laissés après l'échéance : J, J+1, J+2 ; pause à J+3.
GRACE_DAYS: Final = 3

STAGES: Final[tuple[Stage, ...]] = ("eve", "due", "last", "suspended")
_RANK: Final[dict[str | None, int]] = {None: 0, "eve": 1, "due": 2, "last": 3, "suspended": 4}


@dataclass(frozen=True, slots=True)
class Deadline:
    kind: Kind
    ends_at: datetime


def deadline(
    *,
    status: str,
    trial_ends_at: datetime | None,
    current_period_end: datetime | None,
    is_license: bool,
) -> Deadline | None:
    """L'échéance suivie, ou `None` : licence sur site, période sans fin, déjà suspendue."""
    if is_license or status not in ("trial", "active", "past_due"):
        return None
    if status != "trial" and current_period_end is not None:
        return Deadline("paid", current_period_end)
    if status in ("trial", "past_due") and trial_ends_at is not None:
        return Deadline("trial", trial_ends_at)
    return None


def zone(name: str | None) -> ZoneInfo:
    """Le fuseau de l'entreprise ; un nom inconnu compte en UTC plutôt que d'échouer."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_day(moment: datetime, tz: ZoneInfo) -> date:
    return moment.astimezone(tz).date()


def offset_days(ends_at: datetime, now: datetime, tz: ZoneInfo) -> int:
    """Jours calendaires depuis J : -1 la veille, 0 le jour J, 3 le jour de la pause."""
    return (local_day(now, tz) - local_day(ends_at, tz)).days


def calendar_stage(offset: int) -> Stage | None:
    """L'étape que le calendrier attend ce jour-là."""
    if offset < -1:
        return None
    if offset == -1:
        return "eve"
    if offset <= 1:
        return "due"
    if offset == 2:
        return "last"
    return "suspended"


def next_stage(*, offset: int, done: str | None, done_on: date | None, today: date) -> Stage | None:
    """L'étape à franchir aujourd'hui, ou `None`.

    `done` : la dernière étape franchie pour **cette** échéance (`None` sinon) ;
    `done_on` : le jour (fuseau de l'entreprise) où elle l'a été.
    """
    target = calendar_stage(offset)
    if target is None or _RANK[target] <= _RANK[done]:
        return None
    if done_on is not None and done_on >= today:
        return None  # une étape par jour au plus
    if target == "suspended" and done != "last":
        return "last"  # personne n'est mis en pause sans avoir été prévenu la veille
    return target


def pause_day(ends_at: datetime, tz: ZoneInfo) -> date:
    """Le jour où la boutique est mise en pause (au plus tôt)."""
    return date.fromordinal(local_day(ends_at, tz).toordinal() + GRACE_DAYS)


@dataclass(frozen=True, slots=True)
class Banner:
    """Ce que montre le bandeau ce jour-là (de J-1 à J+2)."""

    kind: Kind
    stage: Literal["eve", "due", "last"]
    ends_at: datetime
    pause_on: date
    #: Jours d'ouverture qui restent avant la pause (1 la veille de la pause).
    days_left: int


def banner(
    *,
    status: str,
    trial_ends_at: datetime | None,
    current_period_end: datetime | None,
    is_license: bool,
    now: datetime,
    timezone: str | None,
) -> Banner | None:
    found = deadline(
        status=status,
        trial_ends_at=trial_ends_at,
        current_period_end=current_period_end,
        is_license=is_license,
    )
    if found is None:
        return None
    tz = zone(timezone)
    stage = calendar_stage(offset_days(found.ends_at, now, tz))
    if stage is None:
        return None
    if stage == "suspended":
        # Pas encore mise en pause (nuit manquée) : le dernier rappel reste affiché.
        stage = "last"
    pause_on = pause_day(found.ends_at, tz)
    days_left = max(1, (pause_on - local_day(now, tz)).days)
    return Banner(found.kind, stage, found.ends_at, pause_on, days_left)


# ------------------------------------------------------------------- les mots

#: Ce que dit chaque étape (cloche, e-mail, message WhatsApp de l'équipe). Ton chaleureux,
#: textes proposés au propriétaire (ADR 0133) ; le bandeau de l'application a les siens,
#: côté front, dans les mêmes termes.


def _what(kind: Kind) -> str:
    return "Votre essai" if kind == "trial" else "Votre abonnement"


def title(stage: Stage, kind: Kind, days_left: int) -> str:
    if stage == "suspended":
        return "Votre boutique est en pause"
    if stage == "last":
        return "Dernier rappel : pause demain"
    if stage == "eve":
        return f"{_what(kind)} se termine demain"
    if days_left >= GRACE_DAYS:
        return f"{_what(kind)} se termine aujourd'hui"
    return f"{_what(kind)} est terminé"


def message(stage: Stage, kind: Kind, plan_name: str, days_left: int) -> str:
    """Le texte de l'étape. « Échéance » est hors du lexique (ADR 0069) : « se termine »."""
    if stage == "suspended":
        return (
            "Votre boutique est en pause. Vos données sont gardées, et tout revient dès le "
            "paiement."
        )
    if stage == "last":
        return (
            "Dernier rappel : sans paiement, votre boutique sera mise en pause demain. Vos "
            "données sont gardées, et tout revient dès le paiement."
        )
    if stage == "eve":
        if kind == "trial":
            return (
                f"Votre essai gratuit de CoGes {plan_name} se termine demain. Pour continuer "
                "sans interruption, choisissez votre offre. Nous sommes là si vous avez une "
                "question."
            )
        return (
            f"Votre abonnement CoGes {plan_name} se termine demain. Pour continuer sans "
            "interruption, renouvelez votre offre. Nous sommes là si vous avez une question."
        )
    when = "se termine aujourd'hui" if days_left >= GRACE_DAYS else "s'est terminé hier"
    days = f"{days_left} jours" if days_left > 1 else "1 jour"
    then = "choisir votre offre" if kind == "trial" else "le renouveler"
    return (
        f"{_what(kind)} {when}. Pas d'inquiétude : votre boutique reste ouverte encore "
        f"{days}, le temps de {then}."
    )
