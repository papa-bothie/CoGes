"""Vérifie que T1 à T40 (§ 10 du Modèle) ont chacun au moins un test, tous verts.

Lit le rapport JUnit du job `integrity` et écrit un tableau T1–T40 dans le résumé du
job GitHub (`$GITHUB_STEP_SUMMARY`). Échoue si un numéro n'a aucun test, ou si l'un
de ses tests a échoué ou a été sauté : « T1–T40 en CI » se lit alors d'un coup d'œil.

Usage : python deploy/scripts/integrity_summary.py rapport.xml
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET  # noqa: S405 - rapport produit par notre propre CI
from collections import defaultdict

NUMBERS = range(1, 41)
#: `test_t25_t28_debts…` couvre T25 à T28 ; `test_t06_negative…` couvre T6.
NAME = re.compile(r"test_t(\d{2})(?:_t(\d{2}))?")


def covered(name: str) -> list[int]:
    match = NAME.search(name)
    if match is None:
        return []
    first = int(match.group(1))
    last = int(match.group(2)) if match.group(2) else first
    return list(range(first, last + 1))


def main(path: str) -> int:
    outcomes: dict[int, list[str]] = defaultdict(list)
    for case in ET.parse(path).getroot().iter("testcase"):  # noqa: S314
        outcome = "passed"
        for tag in ("failure", "error", "skipped"):
            if case.find(tag) is not None:
                outcome = tag
        # Le numéro peut venir du nom du test ou de celui de son fichier.
        where = f"{case.get('classname', '')}.{case.get('name', '')}"
        for number in set(covered(case.get("name", "")) or covered(where)):
            outcomes[number].append(outcome)

    lines = ["## Tests d'intégrité T1–T40", "", "| Test | Cas | Statut |", "|---|---|---|"]
    problems = []
    for number in NUMBERS:
        results = outcomes.get(number, [])
        ok = bool(results) and all(result == "passed" for result in results)
        lines.append(f"| T{number} | {len(results)} | {'✅' if ok else '❌'} |")
        if not ok:
            problems.append(f"T{number}: {results or 'aucun test'}")

    summary = "\n".join(lines) + "\n"
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(summary)
    print(summary)
    for problem in problems:
        print(f"ÉCHEC {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
