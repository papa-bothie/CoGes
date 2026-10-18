"""Registre ghcr.io : quelle image construire, quelles versions supprimer (ADR 0083, 0087).

Deux décisions, toutes deux pures et testées (backend/tests/unit/test_registry_cleanup.py) :

``decide`` — construire, réutiliser ou refuser une version, pour un paquet :
  • un SHA (préproduction) se construit toujours : repousser la même étiquette ne
    remplace que l'image du même commit ;
  • une version vX.Y.Z absente du registre se construit ;
  • présente, elle est **réutilisée** si son image est celle du commit de l'étiquette git
    (même condensat que l'étiquette SHA) : c'est le passage préproduction → production,
    qui déploie exactement ce qui a été essayé ;
  • présente sous une autre image, elle est **refusée** : on ne repousse jamais du code
    différent sous une étiquette existante.

``plan`` — versions à supprimer, d'après la liste de l'API des paquets GitHub :
  • jamais celles qui portent `production` ou `production-previous` (posées par le job
    de déploiement après la fumée de production) : retour arrière et reconstruction du
    VPS en dépendent ;
  • jamais une version sans étiquette (un manifeste enfant d'une image vivante, ou un
    reste que le registre purge seul) ;
  • on garde les KEEP_LATEST plus récentes des autres (la préproduction en cours) ;
  • le reste est supprimé. Quota gratuit de 500 Mo : production, précédente et une
    préproduction, ≈ 3 × 460 Mo par paquet au pire (ADR 0087).

Usage :
  registry_cleanup.py decide --version V --version-digest D1 --sha-digest D2
      → écrit « build » ou « reuse », sort en 1 avec un message si refus ;
  gh api --paginate …/versions | registry_cleanup.py plan
      → écrit les identifiants à supprimer, séparés par des virgules (vide : rien).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

PROTECTED_TAGS = frozenset({"production", "production-previous"})
KEEP_LATEST = 1
RELEASE = re.compile(r"^v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")


class RefusedError(Exception):
    """La version demandée ne doit pas être poussée."""


@dataclass(frozen=True)
class PackageVersion:
    id: int
    created_at: str
    tags: tuple[str, ...]


def decide(version: str, *, version_digest: str, sha_digest: str) -> str:
    """`build`, `reuse`, ou `RefusedError` (voir l'en-tête du module)."""
    if not RELEASE.match(version):
        return "build"
    if not version_digest:
        return "build"
    if sha_digest and sha_digest == version_digest:
        return "reuse"
    raise RefusedError(
        f"{version} existe déjà dans le registre sous une autre image que celle de son "
        "étiquette git : choisissez une nouvelle version."
    )


def plan(versions: Iterable[PackageVersion], *, keep_latest: int = KEEP_LATEST) -> list[int]:
    """Identifiants des versions à supprimer, des plus anciennes aux plus récentes."""
    candidates = [
        version
        for version in versions
        if version.tags and not PROTECTED_TAGS.intersection(version.tags)
    ]
    candidates.sort(key=lambda version: version.created_at, reverse=True)
    doomed = candidates[keep_latest:]
    return [version.id for version in reversed(doomed)]


def parse_versions(payload: str) -> list[PackageVersion]:
    """La réponse de l'API, éventuellement en plusieurs pages concaténées (`--paginate`)."""
    decoder = json.JSONDecoder()
    items: list[dict[str, object]] = []
    position = 0
    text = payload.strip()
    while position < len(text):
        page, position = decoder.raw_decode(text, position)
        items.extend(page if isinstance(page, list) else [page])
        while position < len(text) and text[position].isspace():
            position += 1
    versions = []
    for item in items:
        metadata = item.get("metadata") or {}
        container = metadata.get("container") or {} if isinstance(metadata, dict) else {}
        tags = container.get("tags") or [] if isinstance(container, dict) else []
        versions.append(
            PackageVersion(
                id=int(str(item["id"])),
                created_at=str(item["created_at"]),
                tags=tuple(str(tag) for tag in tags),
            )
        )
    return versions


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    decide_parser = commands.add_parser("decide")
    decide_parser.add_argument("--version", required=True)
    decide_parser.add_argument("--version-digest", default="")
    decide_parser.add_argument("--sha-digest", default="")
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--keep-latest", type=int, default=KEEP_LATEST)
    args = parser.parse_args(argv)

    if args.command == "decide":
        try:
            print(
                decide(
                    args.version,
                    version_digest=args.version_digest,
                    sha_digest=args.sha_digest,
                )
            )
        except RefusedError as refused:
            print(f"::error::{refused}", file=sys.stderr)
            return 1
        return 0

    print(
        ",".join(
            str(i) for i in plan(parse_versions(sys.stdin.read()), keep_latest=args.keep_latest)
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
