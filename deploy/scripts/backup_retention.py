"""Rétention des sauvegardes externes (ADR 0084) : quels fichiers peut-on supprimer ?

Lit sur l'entrée standard la liste des fichiers du stockage (`rclone lsf`), écrit sur la
sortie standard ceux à supprimer. Utilisé par .github/workflows/backup-purge.yml, avec un
compte de stockage DISTINCT de celui qui écrit.

Règle, à la date du jour (UTC), sur les seuls `.dump.age` (ADR 0084, 0088) :
  • les 7 derniers jours : tout est gardé, toujours ;
  • les 7 sauvegardes les plus récentes : gardées, même si elles sont anciennes ;
  • 4 semaines : le premier jour sauvegardé de chaque semaine (sa dernière sauvegarde) ;
  • 12 mois : le premier jour sauvegardé de chaque mois (sa dernière sauvegarde) ;
  • le reste, et l'empreinte `.sha256` qui l'accompagne, est supprimé ; une empreinte
    orpheline n'est jamais touchée.
Un nom qui ne suit pas `coges-AAAA-MM-JJ-HHMM.dump.age[.sha256]` n'est jamais touché.

Usage : rclone lsf coges:… | python3 deploy/scripts/backup_retention.py [--today AAAA-MM-JJ]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from datetime import UTC, date, datetime

NAME = re.compile(r"^coges-(\d{4})-(\d{2})-(\d{2})-(\d{4})\.dump\.age(\.sha256)?$")
KEEP_ALL_DAYS = 7
WEEKLY_DAYS = 28
MONTHLY_DAYS = 366


def to_delete(names: Iterable[str], today: date) -> list[str]:
    """Fichiers à supprimer : chaque dump écarté, et l'empreinte qui l'accompagne.

    Seuls les `.dump.age` décident (ADR 0088) : une empreinte orpheline ne représente
    aucun jour et n'est jamais touchée.
    """
    present = {name.strip() for name in names}
    dumps: dict[str, tuple[date, str]] = {}
    for name in present:
        match = NAME.match(name)
        if match is None or match.group(5):
            continue
        year, month, day, hhmm, _ = match.groups()
        dumps[name] = (date(int(year), int(month), int(day)), hhmm)

    # La dernière sauvegarde de chaque jour représente ce jour.
    last_of_day: dict[date, str] = {}
    for day, hhmm in dumps.values():
        if day not in last_of_day or hhmm > last_of_day[day]:
            last_of_day[day] = hhmm
    days = sorted(last_of_day)
    # Le premier jour sauvegardé de chaque semaine et de chaque mois, et non le dimanche
    # ou le 1er exacts : une semaine sans dimanche garde quand même sa sauvegarde.
    first_of_week: dict[tuple[int, int], date] = {}
    first_of_month: dict[tuple[int, int], date] = {}
    for day in days:
        first_of_week.setdefault((day.isocalendar().year, day.isocalendar().week), day)
        first_of_month.setdefault((day.year, day.month), day)
    weekly = set(first_of_week.values())
    monthly = set(first_of_month.values())
    # Plancher : les KEEP_ALL_DAYS sauvegardes les plus récentes restent, même quand
    # la chaîne s'est arrêtée depuis des semaines.
    newest = set(sorted(dumps, key=lambda name: dumps[name], reverse=True)[:KEEP_ALL_DAYS])

    def keep(name: str) -> bool:
        day, hhmm = dumps[name]
        age = (today - day).days
        if age < KEEP_ALL_DAYS or name in newest:
            return True
        if hhmm != last_of_day[day]:
            return False
        if day in weekly and age < WEEKLY_DAYS:
            return True
        return day in monthly and age < MONTHLY_DAYS

    doomed: list[str] = []
    for name in dumps:
        if not keep(name):
            doomed.append(name)
            if f"{name}.sha256" in present:
                doomed.append(f"{name}.sha256")
    return sorted(doomed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    today = args.today or datetime.now(UTC).date()
    for name in to_delete(sys.stdin, today):
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
