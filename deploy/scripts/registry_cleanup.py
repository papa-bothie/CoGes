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
  • jamais une version citée par un canal du sur-site (`deploy/onprem/canal/stable.json`
    ou `test.json` de `main`), par son étiquette ou par l'un de ses digests : les PC des
    clients tirent ces images (ADR 0128, 0131) ;
  • jamais les KEEP_RELEASES plus hautes vX.Y.Z (ordre des numéros) : installation et
    retour arrière d'un PC sur site, préproduction d'une version ;
  • parmi les versions sans étiquette vX.Y.Z (les SHA de préproduction), on garde les
    KEEP_LATEST plus récentes ;
  • le reste est supprimé. Les paquets sont publics : le quota de 500 Mo des paquets
    privés ne s'applique plus (ADR 0131, qui amende 0087).

Un canal illisible (JSON faux, format inconnu, version mal formée) arrête le plan sans
rien supprimer ; un canal absent (aucune version publiée) ne protège rien.

Usage :
  registry_cleanup.py decide --version V --version-digest D1 --sha-digest D2
      → écrit « build » ou « reuse », sort en 1 avec un message si refus ;
  gh api --paginate …/versions | registry_cleanup.py plan [--channel stable.json …]
      → écrit les identifiants à supprimer, séparés par des virgules (vide : rien) ;
        sort en 1 sans rien écrire si un canal donné est illisible.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

PROTECTED_TAGS = frozenset({"production", "production-previous"})
KEEP_LATEST = 1
KEEP_RELEASES = 3
RELEASE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?$")
CHANNEL_FORMAT = "COGES-CANAL-1"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class RefusedError(Exception):
    """La version demandée ne doit pas être poussée."""


class ChannelError(Exception):
    """Un canal du sur-site est illisible : rien ne doit être supprimé."""


@dataclass(frozen=True)
class PackageVersion:
    id: int
    created_at: str
    tags: tuple[str, ...]
    # Le condensat du manifeste (`name` dans l'API des paquets GitHub).
    digest: str = ""


@dataclass(frozen=True)
class Channels:
    """Ce que les canaux du sur-site citent : étiquettes vX.Y.Z et digests d'images."""

    tags: frozenset[str] = field(default_factory=frozenset)
    digests: frozenset[str] = field(default_factory=frozenset)


def _release_key(tag: str) -> tuple[int, int, int, int, str] | None:
    """Ordre des numéros ; une préversion (`-rc.1`) passe avant sa version."""
    match = RELEASE.match(tag)
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre or "")


def _highest_release(version: PackageVersion) -> tuple[int, int, int, int, str] | None:
    keys = [key for key in map(_release_key, version.tags) if key is not None]
    return max(keys) if keys else None


def decide(version: str, *, version_digest: str, sha_digest: str) -> str:
    """`build`, `reuse`, ou `RefusedError` (voir l'en-tête du module)."""
    if _release_key(version) is None:
        return "build"
    if not version_digest:
        return "build"
    if sha_digest and sha_digest == version_digest:
        return "reuse"
    raise RefusedError(
        f"{version} existe déjà dans le registre sous une autre image que celle de son "
        "étiquette git : choisissez une nouvelle version."
    )


def plan(
    versions: Iterable[PackageVersion],
    *,
    keep_latest: int = KEEP_LATEST,
    keep_releases: int = KEEP_RELEASES,
    channels: Channels | None = None,
) -> list[int]:
    """Identifiants des versions à supprimer, des plus anciennes aux plus récentes."""
    channels = channels or Channels()

    def protected(version: PackageVersion) -> bool:
        return bool(
            PROTECTED_TAGS.intersection(version.tags)
            or channels.tags.intersection(version.tags)
            or (version.digest and version.digest in channels.digests)
        )

    candidates = [version for version in versions if version.tags and not protected(version)]
    releases = [version for version in candidates if _highest_release(version) is not None]
    others = [version for version in candidates if _highest_release(version) is None]

    # Les plus hautes vX.Y.Z, qu'elles soient protégées ailleurs ou non : la production
    # ou un canal n'enlève pas une place aux dernières versions.
    all_releases = sorted(
        (version for version in versions if version.tags and _highest_release(version)),
        key=lambda version: _highest_release(version) or (0, 0, 0, 0, ""),
        reverse=True,
    )
    kept_releases = {version.id for version in all_releases[:keep_releases]}
    others.sort(key=lambda version: version.created_at, reverse=True)

    doomed = [version for version in releases if version.id not in kept_releases]
    doomed += others[keep_latest:]
    doomed.sort(key=lambda version: version.created_at)
    return [version.id for version in doomed]


def read_channels(paths: Iterable[Path]) -> Channels:
    """Les canaux donnés ; un fichier absent ne cite rien, un fichier illisible arrête."""
    tags: set[str] = set()
    digests: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ChannelError(f"{path} : illisible ({error})") from error
        if not isinstance(payload, dict) or payload.get("format") != CHANNEL_FORMAT:
            raise ChannelError(f"{path} : format inconnu (attendu {CHANNEL_FORMAT})")
        version = payload.get("version")
        if not isinstance(version, str) or _release_key(version) is None:
            raise ChannelError(f"{path} : version mal formée ({version!r})")
        images = payload.get("images")
        if not isinstance(images, dict) or not images:
            raise ChannelError(f"{path} : aucune image citée")
        for name, digest in images.items():
            if not isinstance(digest, str) or not DIGEST.match(digest):
                raise ChannelError(f"{path} : digest de {name} mal formé ({digest!r})")
            digests.add(digest)
        tags.add(version)
    return Channels(tags=frozenset(tags), digests=frozenset(digests))


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
                digest=str(item.get("name") or ""),
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
    plan_parser.add_argument("--keep-releases", type=int, default=KEEP_RELEASES)
    plan_parser.add_argument(
        "--channel",
        type=Path,
        action="append",
        default=[],
        help="canal du sur-site (stable.json, test.json) dont les versions restent",
    )
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

    try:
        channels = read_channels(args.channel)
    except ChannelError as error:
        print(f"::error::canal du sur-site {error} : rien n'est supprimé", file=sys.stderr)
        return 1
    doomed = plan(
        parse_versions(sys.stdin.read()),
        keep_latest=args.keep_latest,
        keep_releases=args.keep_releases,
        channels=channels,
    )
    print(",".join(str(i) for i in doomed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
