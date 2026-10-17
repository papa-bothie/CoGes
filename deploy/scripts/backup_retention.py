"""Rétention des sauvegardes externes (ADR 0084) : quels fichiers peut-on supprimer ?

Lit sur l'entrée standard la liste des fichiers du stockage (`rclone lsf`), écrit sur la
sortie standard ceux à supprimer. Utilisé par .github/workflows/backup-purge.yml, avec un
compte de stockage DISTINCT de celui qui écrit.

Règle, à la date du jour (UTC) :
  • les 7 derniers jours : tout est gardé, toujours ;
  • 4 semaines : la sauvegarde du dimanche (la dernière du jour) ;
  • 12 mois : celle du 1er du mois (la dernière du jour) ;
  • le reste, et l'empreinte `.sha256` qui l'accompagne, est supprimé.
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
    dated: dict[str, tuple[date, str]] = {}
    for name in names:
        match = NAME.match(name.strip())
        if match is None:
            continue
        year, month, day, hhmm, _ = match.groups()
        dated[name.strip()] = (date(int(year), int(month), int(day)), hhmm)

    # La dernière sauvegarde de chaque jour représente ce jour.
    last_of_day: dict[date, str] = {}
    for _, (day, hhmm) in dated.items():
        if day not in last_of_day or hhmm > last_of_day[day]:
            last_of_day[day] = hhmm

    def keep(day: date, hhmm: str) -> bool:
        age = (today - day).days
        if age < KEEP_ALL_DAYS:
            return True
        if hhmm != last_of_day[day]:
            return False
        if day.weekday() == 6 and age < WEEKLY_DAYS:
            return True
        return day.day == 1 and age < MONTHLY_DAYS

    return sorted(name for name, (day, hhmm) in dated.items() if not keep(day, hhmm))


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
