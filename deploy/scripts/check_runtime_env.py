"""Garde-fou 2 de l'ADR 0042 : le DSN de `coges_owner` n'existe que dans le job de migration.

Échoue (code 1) si l'on trouve, dans un environnement d'**exécution** :

* une variable `COGES_DATABASE_URL_OWNER` (ou sa jumelle de test) ;
* une valeur quelconque qui désigne l'utilisateur `coges_owner` dans un DSN.

Deux sources sont contrôlées :

1. `deploy/docker-compose.worker.yml` (zone B), lu tel quel ;
2. les variables du projet Vercel (zone A), lues par l'API Vercel avec
   `VERCEL_TOKEN`, `VERCEL_PROJECT_ID` et, pour une équipe, `VERCEL_TEAM_ID`.
   Sans jeton, ce contrôle est sauté **et le dit** : la CI de déploiement, elle, le
   fournit toujours.

Usage : python deploy/scripts/check_runtime_env.py [--compose FICHIER] [--require-vercel]
Bibliothèque standard seulement : le script tourne avant toute installation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path

FORBIDDEN_KEYS = frozenset({"COGES_DATABASE_URL_OWNER", "COGES_TEST_DATABASE_URL_OWNER"})
#: `postgresql+psycopg://coges_owner:…@` — l'utilisateur d'un DSN, quel que soit le schéma.
OWNER_IN_DSN = re.compile(r"://coges_owner(?::|@)")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSE = REPO_ROOT / "deploy" / "docker-compose.worker.yml"


def violations(pairs: Iterable[tuple[str, str]], *, source: str) -> list[str]:
    """Variables interdites parmi des couples (nom, valeur)."""
    found: list[str] = []
    for key, value in pairs:
        if key in FORBIDDEN_KEYS:
            found.append(f"{source} : la variable {key} ne doit pas exister à l'exécution")
        elif OWNER_IN_DSN.search(value or ""):
            found.append(f"{source} : {key} désigne l'utilisateur coges_owner")
    return found


def compose_violations(text: str, *, source: str) -> list[str]:
    """Le fichier compose est lu comme du texte : toute mention suffit à refuser."""
    found = [
        f"{source} : mention de {key}" for key in sorted(FORBIDDEN_KEYS) if key in text
    ]
    if OWNER_IN_DSN.search(text):
        found.append(f"{source} : un DSN désigne l'utilisateur coges_owner")
    return found


def vercel_env(token: str, project: str, team: str | None) -> list[tuple[str, str]]:
    query = {"decrypt": "true"}
    if team:
        query["teamId"] = team
    url = (
        f"https://api.vercel.com/v9/projects/{urllib.parse.quote(project)}/env?"
        + urllib.parse.urlencode(query)
    )
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - URL fixe
        payload = json.load(response)
    return [(item["key"], str(item.get("value", ""))) for item in payload.get("envs", [])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument(
        "--require-vercel", action="store_true", help="Échouer si le jeton Vercel manque"
    )
    args = parser.parse_args(argv)

    problems = compose_violations(args.compose.read_text(encoding="utf-8"), source=str(args.compose))

    token = os.environ.get("VERCEL_TOKEN")
    project = os.environ.get("VERCEL_PROJECT_ID")
    if token and project:
        problems += violations(
            vercel_env(token, project, os.environ.get("VERCEL_TEAM_ID")), source="Vercel"
        )
    elif args.require_vercel:
        problems.append("VERCEL_TOKEN et VERCEL_PROJECT_ID sont requis pour contrôler Vercel")
    else:
        print("Contrôle Vercel sauté : VERCEL_TOKEN ou VERCEL_PROJECT_ID absent.")

    for problem in problems:
        print(f"REFUS — {problem}", file=sys.stderr)
    if not problems:
        print("OK — aucun DSN propriétaire dans les environnements d'exécution.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
