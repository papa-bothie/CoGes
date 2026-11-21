"""Publier une version de CoGes pour les PC des clients (canal de mise à jour, ADR 0128).

Lancé par le propriétaire, chez CoGes, depuis une étiquette DÉJÀ publiée (images sur
ghcr.io, workflow « Déployer ») : lit les digests des trois images, télécharge l'archive de
l'étiquette, calcule l'empreinte du programme (contenu de deploy/onprem), et écrit
`deploy/onprem/canal/<canal>.json`. Le fichier part ensuite par une pull request sur `main` :
c'est elle qui « publie ». Chaque PC lit son canal sur raw.githubusercontent.com.

    python3 deploy/onprem/canal/publier.py --version v0.4.0 --canal test --depuis-minimum v0.4.0 \\
        --note "Corrige l'impression du ticket."

Le PC ne croit jamais une étiquette : il tire les images PAR DIGEST, et refuse si l'étiquette
ne pointe plus au même endroit. Le canal n'est pas signé (choix du propriétaire, ADR 0128) :
le champ `signature` est réservé, toujours `null` pour l'instant.

Bibliothèque standard seulement (aucune dépendance sur le poste du propriétaire).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

FORMAT = "COGES-CANAL-1"
CHANNELS = ("stable", "test")
IMAGES = ("front", "api", "worker")
REGISTRY = "ghcr.io/papa-bothie/coges"
ARCHIVE_URL = "https://github.com/papa-bothie/CoGes/archive/refs/tags/{version}.zip"
VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
DOCKER_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
#: Dans l'archive de GitHub : « CoGes-0.4.0/deploy/onprem/… ». Seul ce dossier est posé sur
#: le PC (Install-Programme, CoGes.Install.ps1), et seul lui compte dans l'empreinte.
ENTRY = re.compile(r"^[^/]+/deploy/onprem/(.+)$")
#: Sans lui, la version ne saurait pas se mettre à jour seule ensuite.
REQUIRED = ("windows/mise-a-jour.ps1", "windows/CoGes.Install.ps1", "docker-compose.yml")
MANIFEST_TYPES = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
FIELDS = (
    "format",
    "canal",
    "version",
    "publiee_le",
    "depuis_minimum",
    "images",
    "programme",
    "docker_desktop_minimum",
    "note",
    "signature",
)


class CanalError(Exception):
    """Refus expliqué en français."""


# ---------------------------------------------------------------------------- versions


def version_key(version: str) -> tuple[int, int, int]:
    match = VERSION.match(version or "")
    if not match:
        raise CanalError(f"« {version} » n'est pas une version vX.Y.Z")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


# ---------------------------------------------------------------------------- programme


def programme_digest(archive: Path) -> tuple[str, int]:
    """Empreinte du CONTENU de deploy/onprem dans l'archive : sha256 du texte
    « <sha256 du fichier>  <chemin>\\n » trié par chemin. Indépendante de la compression du
    .zip (GitHub fabrique ses archives à la demande). Même calcul que
    Get-CogesProgrammeDigest (CoGes.Install.ps1), vérifié par un test."""
    lines: list[str] = []
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            match = ENTRY.match(info.filename)
            if not match or info.is_dir() or info.filename.endswith("/"):
                continue
            relative = match.group(1)
            if re.search(r"(^|/)__pycache__(/|$)", relative):
                continue
            if ".." in relative.split("/"):
                raise CanalError(f"chemin refusé dans l'archive : {info.filename}")
            lines.append(f"{hashlib.sha256(zipped.read(info)).hexdigest()}  {relative}\n")
    if not lines:
        raise CanalError("l'archive ne contient pas deploy/onprem")
    lines.sort(key=lambda line: line.split("  ", 1)[1])
    present = {line.split("  ", 1)[1].rstrip("\n") for line in lines}
    missing = [name for name in REQUIRED if name not in present]
    if missing:
        raise CanalError(
            "le programme de cette version ne sait pas se mettre à jour seul "
            f"(absents : {', '.join(missing)})"
        )
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest(), len(lines)


# ---------------------------------------------------------------------------- registre


def _split_registry(registry: str) -> tuple[str, str]:
    host, _, path = registry.partition("/")
    if not host or not path:
        raise CanalError(f"registre « {registry} » : hôte/chemin attendu")
    scheme = "http" if host.split(":")[0] in ("localhost", "127.0.0.1") else "https"
    return f"{scheme}://{host}", path


def _bearer(header: str, repository: str) -> str:
    """Jeton anonyme du registre (ghcr.io : paquets publics), d'après WWW-Authenticate."""
    if not header.lower().startswith("bearer "):
        raise CanalError(f"authentification du registre inattendue : {header}")
    params = dict(re.findall(r'(\w+)="([^"]*)"', header))
    realm = params.pop("realm", "")
    params.setdefault("scope", f"repository:{repository}:pull")
    with urllib.request.urlopen(  # noqa: S310 (adresse donnée par le registre)
        f"{realm}?{urllib.parse.urlencode(params)}", timeout=30
    ) as response:
        data = json.loads(response.read())
    token = data.get("token") or data.get("access_token")
    if not token:
        raise CanalError("le registre n'a pas donné de jeton anonyme")
    return str(token)


def registry_digest(registry: str, image: str, tag: str) -> str:
    """Le digest vers lequel pointe `<registre>/<image>:<tag>` (en-tête Docker-Content-Digest)."""
    base, path = _split_registry(registry)
    repository = f"{path}/{image}"
    url = f"{base}/v2/{repository}/manifests/{tag}"
    headers = {"Accept": MANIFEST_TYPES}
    for _attempt in range(2):
        request = urllib.request.Request(url, method="HEAD", headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                digest = response.headers.get("Docker-Content-Digest", "")
                if not DIGEST.match(digest):
                    raise CanalError(f"{repository}:{tag} : digest illisible ({digest!r})")
                return digest
        except urllib.error.HTTPError as error:
            if error.code == 401 and "Authorization" not in headers:
                headers["Authorization"] = "Bearer " + _bearer(
                    error.headers.get("WWW-Authenticate", ""), repository
                )
                continue
            if error.code == 404:
                raise CanalError(f"{repository}:{tag} n'existe pas sur le registre") from error
            raise CanalError(f"{repository}:{tag} : le registre répond {error.code}") from error
    raise CanalError(f"{repository}:{tag} : accès refusé par le registre")


# ---------------------------------------------------------------------------- canal


def build_canal(
    *,
    canal: str,
    version: str,
    published: str,
    minimum: str,
    digests: dict[str, str],
    programme: tuple[str, int],
    docker_desktop_minimum: str | None,
    note: str,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "format": FORMAT,
        "canal": canal,
        "version": version,
        "publiee_le": published,
        "depuis_minimum": minimum,
        "images": {name: digests[name] for name in IMAGES},
        "programme": {"sha256": programme[0], "fichiers": programme[1]},
        "docker_desktop_minimum": docker_desktop_minimum,
        "note": note,
        # Réservé à une signature future (ADR 0128) : le format ne changera pas.
        "signature": None,
    }
    problems = canal_problems(data)
    if problems:
        raise CanalError("; ".join(problems))
    return data


def canal_problems(data: Any) -> list[str]:
    """Ce qui ne va pas dans un canal (les mêmes règles que Read-CogesChannel côté PC)."""
    if not isinstance(data, dict):
        return ["le canal n'est pas un objet JSON"]
    found: list[str] = []
    missing = [name for name in FIELDS if name not in data]
    if missing:
        found.append("champs absents : " + ", ".join(missing))
        return found
    if data["format"] != FORMAT:
        found.append(f"format {data['format']!r}, {FORMAT} attendu")
    if data["canal"] not in CHANNELS:
        found.append(f"canal {data['canal']!r} inconnu")
    for name in ("version", "depuis_minimum"):
        if not isinstance(data[name], str) or not VERSION.match(data[name]):
            found.append(f"{name} : vX.Y.Z attendu")
    if not found and version_key(data["depuis_minimum"]) > version_key(data["version"]):
        found.append("depuis_minimum est plus récent que la version")
    try:
        dt.date.fromisoformat(str(data["publiee_le"]))
    except ValueError:
        found.append("publiee_le : date AAAA-MM-JJ attendue")
    images = data["images"]
    if not isinstance(images, dict) or set(images) != set(IMAGES):
        found.append("images : front, api et worker attendues")
    else:
        found += [
            f"images.{name} : sha256:<64 hexadécimaux> attendu"
            for name in IMAGES
            if not isinstance(images[name], str) or not DIGEST.match(images[name])
        ]
    programme = data["programme"]
    if (
        not isinstance(programme, dict)
        or not isinstance(programme.get("sha256"), str)
        or not HEX64.match(programme["sha256"])
        or not isinstance(programme.get("fichiers"), int)
        or programme["fichiers"] < 1
    ):
        found.append("programme : sha256 et nombre de fichiers attendus")
    minimum = data["docker_desktop_minimum"]
    if minimum is not None and (not isinstance(minimum, str) or not DOCKER_VERSION.match(minimum)):
        found.append("docker_desktop_minimum : X.Y.Z ou null attendu")
    if not isinstance(data["note"], str) or not 1 <= len(data["note"].strip()) <= 300:
        found.append("note : une ou deux phrases (300 caractères au plus)")
    if data["signature"] is not None:
        found.append("signature : réservée, null attendu")
    return found


def dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------- commande


def _download(version: str, folder: Path) -> Path:
    target = folder / f"coges-{version}.zip"
    url = ARCHIVE_URL.format(version=version)
    try:
        with urllib.request.urlopen(url, timeout=600) as response:  # noqa: S310
            target.write_bytes(response.read())
    except urllib.error.URLError as error:
        raise CanalError(f"l'archive de {version} ne se télécharge pas ({url})") from error
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--version", required=True, help="étiquette déjà publiée, vX.Y.Z")
    parser.add_argument("--canal", required=True, choices=CHANNELS)
    parser.add_argument(
        "--depuis-minimum",
        required=True,
        help="la plus ancienne version qui peut sauter directement à celle-ci",
    )
    parser.add_argument("--note", required=True, help="une ou deux phrases pour le technicien")
    parser.add_argument("--docker-desktop-minimum", default=None, help="X.Y.Z, si besoin")
    parser.add_argument("--registre", default=REGISTRY, help=argparse.SUPPRESS)
    parser.add_argument("--archive", type=Path, default=None, help="archive déjà téléchargée")
    parser.add_argument("--date", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--sortie", type=Path, default=None, help="défaut : <canal>.json ici")
    parser.add_argument("--forcer-plus-ancienne", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    output = args.sortie or Path(__file__).resolve().parent / f"{args.canal}.json"
    try:
        version_key(args.version)
        version_key(args.depuis_minimum)
        if output.exists() and not args.forcer_plus_ancienne:
            current = json.loads(output.read_text(encoding="utf-8")).get("version", "v0.0.0")
            if version_key(args.version) < version_key(current):
                raise CanalError(
                    f"{output.name} annonce déjà {current}, plus récente que {args.version} : "
                    "le canal ne fait jamais redescendre les PC (Restaurer, ou "
                    "RevenirVersionPrecedente sur place)"
                )
        digests = {name: registry_digest(args.registre, name, args.version) for name in IMAGES}
        with tempfile.TemporaryDirectory() as folder:
            archive = args.archive or _download(args.version, Path(folder))
            programme = programme_digest(archive)
        data = build_canal(
            canal=args.canal,
            version=args.version,
            published=args.date or dt.date.today().isoformat(),
            minimum=args.depuis_minimum,
            digests=digests,
            programme=programme,
            docker_desktop_minimum=args.docker_desktop_minimum,
            note=args.note.strip(),
        )
    except (CanalError, OSError, zipfile.BadZipFile) as error:
        print(f"ÉCHEC — {error}", file=sys.stderr)
        return 1
    output.write_text(dumps(data), encoding="utf-8", newline="\n")
    print(f"OK — {output} : {args.version} sur le canal {args.canal}")
    for name in IMAGES:
        print(f"  {name:6} {digests[name]}")
    print(f"  programme {programme[0]} ({programme[1]} fichiers)")
    print("Ensuite : pull request sur main avec ce seul fichier (guide, « Publier une version »).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
