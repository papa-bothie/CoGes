"""Contrôle des réglages d'une installation CoGes sur site (ADR 0124).

À lancer AVANT le premier démarrage et après chaque modification de `coges.env`. Chaque
refus dit quoi corriger. Deux sources :

1. `--env-file` : le fichier de réglages du client. Refusés : un secret trop court, resté
   vide ou à une valeur de modèle, deux secrets identiques, une étiquette d'image vide ou
   `latest`, un port et une adresse qui ne concordent pas, un service facultatif posé
   (éteints sur site, lot 1) ou à moitié posé, un DSN ou une URL Redis écrits à la main
   (le compose les compose lui-même), COGES_ENV autre que `production`.
2. `--rendered` (facultatif) : le rendu de `docker compose … --profile tools config
   --format json`. Refusés : un DSN d'exécution qui ne désigne pas son rôle (liste blanche
   de l'ADR 0088) ou un autre hôte que `postgres`, le DSN propriétaire ailleurs que dans
   `migrate`, une URL Redis hors du réseau interne, COGES_ENV autre que `production`, une
   image sans étiquette ou en `latest`, un port publié hors de 127.0.0.1.

Garde-fou « jamais la production » : toute valeur qui contient `neon.tech`, le domaine de
production ou un Redis hébergé est refusée. Une installation sur site ne peut pas, même par
erreur de copier-coller, se brancher sur la base ou les services des utilisateurs actuels.

Il n'exige ni Neon, ni sslmode, ni domaine public (à l'inverse de check_runtime_env.py).

Sur le PC du client (pas de Python), il tourne dans l'image worker déjà téléchargée :
voir docs/runbooks/sur-site.md. Bibliothèque standard seulement ; aucun fichier lu hors
de ceux passés en argument.

Usage : python check_onprem_env.py --env-file FICHIER [--rendered FICHIER.json]
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

MIN_SECRET_LENGTH = 32
#: Secrets du modèle, tous exigés. Hexadécimal seulement : ni « $ » ni « # », que le
#: compose ou le fichier d'environnement interpréteraient.
SECRETS = (
    "COGES_POSTGRES_PASSWORD",
    "COGES_OWNER_PASSWORD",
    "COGES_APP_PASSWORD",
    "COGES_RELAY_PASSWORD",
    "COGES_ANALYTICS_PASSWORD",
    "COGES_PLATFORM_PASSWORD",
    "COGES_REDIS_PASSWORD",
    "COGES_JWT_SECRET",
)
HEXADECIMAL = re.compile(r"[0-9a-fA-F]+")
#: Valeurs de modèle ou d'exemple : jamais un vrai secret.
PLACEHOLDERS = ("change-me", "changeme", "a-remplir", "exemple", "example", "secret", "password")

#: DSN d'exécution et le seul rôle que chacun peut désigner (liste blanche de l'ADR 0088 ;
#: un test la compare à celle de check_runtime_env.py).
RUNTIME_DSNS: dict[str, str] = {
    "COGES_DATABASE_URL_APP": "coges_app",
    "COGES_DATABASE_URL_RELAY": "coges_relay",
    "COGES_DATABASE_URL_ANALYTICS": "coges_analytics",
    "COGES_DATABASE_URL_PLATFORM": "coges_app_platform",
}
OWNER_DSN = "COGES_DATABASE_URL_OWNER"
#: Le seul service qui reçoit le DSN propriétaire : ponctuel, jamais lancé par `up`.
OWNER_SERVICES = frozenset({"migrate"})
#: Les seuls hôtes de données : les services du compose, sur le réseau interne.
DATABASE_HOST = "postgres"
REDIS_HOST = "redis"
#: Services dont l'image est celle de CoGes (étiquette obligatoire).
APP_IMAGES = re.compile(r"/(front|api|worker)(:|$)")

#: « Jamais la production » : la base (Neon), le domaine public, les anciens hébergeurs et
#: tout Redis hébergé.
PRODUCTION_MARKERS = (
    "neon.tech",
    "coges.app",
    "vercel.app",
    "redis-cloud.com",
    "redislabs.com",
    "upstash.io",
    "rediss://",
)

#: Services facultatifs : éteints sur site pour ce lot (le réseau n'a aucune sortie).
OPTIONAL_GROUPS: dict[str, tuple[str, ...]] = {
    "les notifications (VAPID)": (
        "COGES_VAPID_PUBLIC_KEY",
        "COGES_VAPID_PRIVATE_KEY",
        "COGES_VAPID_SUBJECT",
    ),
    "les photos (Cloudinary)": (
        "COGES_CLOUDINARY_CLOUD_NAME",
        "COGES_CLOUDINARY_API_KEY",
        "COGES_CLOUDINARY_API_SECRET",
    ),
}
OPTIONAL_SINGLES = (
    "COGES_SMTP_HOST",
    "COGES_SENTRY_DSN",
    "COGES_JOB_PING_URLS",
    "COGES_ACCESS_TEAM_DOMAIN",
    "COGES_ACCESS_AUD",
    "COGES_CLOUDFLARE_TUNNEL_TOKEN",
)
PUBLIC_URL = re.compile(r"http://localhost(?::(\d{1,5}))?")


def read_text(path: Path) -> str:
    """Texte d'un fichier écrit sous Windows : UTF-8 (avec ou sans BOM) ou UTF-16
    (la redirection `>` de PowerShell 5)."""
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def read_env_file(text: str) -> dict[str, str]:
    """Couples NOM=valeur, sans rien exécuter. Les fins de ligne Windows (CRLF) du
    Bloc-notes sont acceptées : `docker compose --env-file` les lit de la même façon
    (vérifié). Seuls les fichiers du dossier du programme doivent rester en LF."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def production_marker(value: str) -> str | None:
    lowered = urllib.parse.unquote(value).lower()
    return next((marker for marker in PRODUCTION_MARKERS if marker in lowered), None)


def dsn_users(value: str) -> list[str]:
    """Utilisateurs que désigne un DSN, décodés : avant « @ » et en `?user=`."""
    parsed = urllib.parse.urlsplit(value)
    users = [urllib.parse.unquote(parsed.username)] if parsed.username else []
    users += urllib.parse.parse_qs(parsed.query).get("user", [])
    return users


def dsn_violations(key: str, value: str, *, source: str) -> list[str]:
    """Un DSN PostgreSQL : son rôle attendu, et l'hôte `postgres` du compose."""
    found: list[str] = []
    role = "coges_owner" if key == OWNER_DSN else RUNTIME_DSNS.get(key)
    users = dsn_users(value)
    if role is None:
        found.append(f"{source} : {key} n'est pas un DSN connu de CoGes : retirez-le")
    elif users != [role]:
        found.append(
            f"{source} : {key} doit se connecter sous {role} (lu : {', '.join(users) or 'aucun'})"
        )
    host = urllib.parse.urlsplit(value).hostname
    if host != DATABASE_HOST:
        found.append(
            f"{source} : {key} vise l'hôte « {host or 'aucun'} » : sur site, la seule base "
            f"est le service « {DATABASE_HOST} » de ce PC"
        )
    return found


def secret_violations(values: dict[str, str], *, source: str) -> list[str]:
    found: list[str] = []
    for key in SECRETS:
        value = values.get(key, "")
        if not value:
            found.append(f"{source} : {key} est vide : tirez un mot de passe (commande du modèle)")
        elif any(word in value.lower() for word in PLACEHOLDERS):
            found.append(
                f"{source} : {key} garde une valeur de modèle : tirez un vrai mot de passe"
            )
        elif len(value) < MIN_SECRET_LENGTH:
            found.append(
                f"{source} : {key} compte {len(value)} caractères, il en faut "
                f"{MIN_SECRET_LENGTH} au moins"
            )
        elif not HEXADECIMAL.fullmatch(value):
            found.append(
                f"{source} : {key} doit être en hexadécimal (0-9 et a-f) : un « $ » ou un "
                "« # » serait mal lu"
            )
    filled = [values[key] for key in SECRETS if values.get(key)]
    if len(set(filled)) != len(filled):
        found.append(
            f"{source} : deux mots de passe sont identiques : tirez-en un différent pour chacun"
        )
    return found


def mfa_key_violations(values: dict[str, str], *, source: str) -> list[str]:
    """COGES_MFA_ENCRYPTION_KEY (ADR 0105) : 32 octets en base64url ; sans elle, l'API ne
    démarre pas."""
    value = values.get("COGES_MFA_ENCRYPTION_KEY", "")
    if not value:
        return [f"{source} : COGES_MFA_ENCRYPTION_KEY est vide : tirez la clé (commande du modèle)"]
    try:
        key = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error):
        key = b""
    if len(key) != 32 or base64.urlsafe_b64encode(key).decode().rstrip("=") != value.rstrip("="):
        return [
            f"{source} : COGES_MFA_ENCRYPTION_KEY doit faire 43 caractères (32 octets en "
            "base64url) : retirez-la avec la commande du modèle"
        ]
    if len(set(key)) == 1:
        return [f"{source} : COGES_MFA_ENCRYPTION_KEY garde une valeur de modèle"]
    return []


def tag_violations(tag: str, *, source: str, name: str = "COGES_IMAGE_TAG") -> list[str]:
    if not tag:
        return [f"{source} : {name} est vide : écrivez la version donnée par CoGes (vX.Y.Z)"]
    if tag.lower() == "latest":
        return [
            f"{source} : {name} vaut « latest » : écrivez une version précise (vX.Y.Z), "
            "sinon une mise à jour partirait sans prévenir"
        ]
    return []


def optional_violations(values: dict[str, str], *, source: str) -> list[str]:
    found: list[str] = []
    for label, keys in OPTIONAL_GROUPS.items():
        present = [key for key in keys if values.get(key)]
        if present and len(present) < len(keys):
            missing = ", ".join(key for key in keys if key not in present)
            found.append(
                f"{source} : {label} sont à moitié posés ({missing} manque) : videz "
                f"{', '.join(present)}"
            )
        elif present:
            found.append(
                f"{source} : {label} sont éteints sur site pour l'instant : videz "
                f"{', '.join(present)}"
            )
    for key in OPTIONAL_SINGLES:
        if values.get(key):
            found.append(f"{source} : {key} est éteint sur site pour l'instant : videz-le")
    if values.get("COGES_SIGNUP_ENABLED", "false").lower() not in {"", "false"}:
        found.append(f"{source} : COGES_SIGNUP_ENABLED doit rester à false sur site")
    return found


def address_violations(values: dict[str, str], *, source: str) -> list[str]:
    """Le port publié et l'adresse tapée dans le navigateur vont ensemble."""
    port = values.get("COGES_HTTP_PORT", "") or "80"
    url = values.get("COGES_PUBLIC_URL", "") or "http://localhost"
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        return [f"{source} : COGES_HTTP_PORT doit être un numéro de port (80, 8080…)"]
    match = PUBLIC_URL.fullmatch(url)
    if match is None:
        return [
            f"{source} : COGES_PUBLIC_URL doit valoir http://localhost (ou "
            "http://localhost:PORT) : CoGes sur site ne s'ouvre que depuis ce PC"
        ]
    expected = "http://localhost" if port == "80" else f"http://localhost:{port}"
    if url != expected:
        return [
            f"{source} : COGES_HTTP_PORT={port} va avec COGES_PUBLIC_URL={expected} "
            f"(lu : {url}) : changez les deux lignes ensemble"
        ]
    return []


def env_file_violations(text: str, *, source: str) -> list[str]:
    """Règles du fichier de réglages du client."""
    found: list[str] = []
    values = read_env_file(text)

    for key, value in values.items():
        marker = production_marker(value)
        if marker is not None:
            found.append(
                f"{source} : {key} contient « {marker} » : ce sont les services de la "
                "production. Une installation sur site ne s'y branche jamais : retirez la ligne"
            )
        elif key.startswith("COGES_DATABASE_URL") or key.startswith("COGES_TEST_DATABASE_URL"):
            found += dsn_violations(key, value, source=source) if value else []
            found.append(
                f"{source} : {key} n'a rien à faire ici : le compose compose lui-même les "
                "adresses de la base à partir des mots de passe. Retirez la ligne"
            )
        elif key == "COGES_REDIS_URL":
            host = urllib.parse.urlsplit(value).hostname
            if host != REDIS_HOST:
                found.append(
                    f"{source} : COGES_REDIS_URL vise « {host or 'aucun'} », hors du réseau "
                    "interne de ce PC"
                )
            found.append(
                f"{source} : COGES_REDIS_URL n'a rien à faire ici : le compose la compose "
                "lui-même. Retirez la ligne"
            )

    env = values.get("COGES_ENV")
    if env is not None and env != "production":
        found.append(
            f"{source} : COGES_ENV vaut « {env} » : sur site, c'est toujours production "
            "(retirez la ligne, le compose le pose)"
        )
    found += tag_violations(values.get("COGES_IMAGE_TAG", ""), source=source)
    if not values.get("COGES_IMAGE_REGISTRY", "ghcr.io/papa-bothie/coges"):
        found.append(f"{source} : COGES_IMAGE_REGISTRY est vide : remettez la ligne du modèle")
    found += secret_violations(values, source=source)
    found += mfa_key_violations(values, source=source)
    found += address_violations(values, source=source)
    found += optional_violations(values, source=source)
    return found


def _environment(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
    return {str(key): "" if value is None else str(value) for key, value in env.items()}


def rendered_violations(config: dict[str, Any], *, source: str) -> list[str]:
    """Règles du compose rendu : ce que chaque conteneur recevra vraiment."""
    found: list[str] = []
    services: dict[str, dict[str, Any]] = config.get("services") or {}
    for name, service in sorted(services.items()):
        where = f"{source} : service {name}"
        env = _environment(service)

        for key, value in env.items():
            marker = production_marker(value)
            if marker is not None:
                found.append(f"{where} : {key} contient « {marker} » (services de la production)")
            if key == OWNER_DSN or (value and "coges_owner" in dsn_users(value)):
                if name not in OWNER_SERVICES:
                    found.append(
                        f"{where} : reçoit le DSN de coges_owner ({key}) : il est réservé au "
                        "service ponctuel migrate"
                    )
                elif key == OWNER_DSN:
                    found += dsn_violations(key, value, source=where)
            elif key.startswith("COGES_DATABASE_URL"):
                found += dsn_violations(key, value, source=where)
            elif key == "COGES_REDIS_URL":
                host = urllib.parse.urlsplit(value).hostname
                if host != REDIS_HOST:
                    found.append(
                        f"{where} : COGES_REDIS_URL vise « {host or 'aucun'} », hors du "
                        "réseau interne"
                    )

        if "COGES_ENV" in env and env["COGES_ENV"] != "production":
            found.append(f"{where} : COGES_ENV vaut « {env['COGES_ENV']} », pas production")

        image = str(service.get("image", ""))
        if APP_IMAGES.search(image):
            tag = image.rsplit(":", 1)[1] if ":" in image.rsplit("/", 1)[-1] else ""
            found += tag_violations(tag, source=where, name="l'étiquette de l'image")

        for port in service.get("ports") or []:
            host_ip = port.get("host_ip") if isinstance(port, dict) else None
            if host_ip != "127.0.0.1":
                found.append(
                    f"{where} : publie un port hors de la boucle locale "
                    f"({host_ip or 'toutes les interfaces'}) : seul 127.0.0.1 est permis"
                )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env-file", type=Path, required=True, help="coges.env du client")
    parser.add_argument(
        "--rendered",
        type=Path,
        help="rendu JSON de « docker compose --profile tools config --format json »",
    )
    args = parser.parse_args(argv)

    try:
        problems = env_file_violations(read_text(args.env_file), source=args.env_file.name)
    except OSError as exc:
        print(f"REFUS — {args.env_file} est illisible ({exc.strerror})", file=sys.stderr)
        return 1
    if args.rendered is not None:
        config = json.loads(read_text(args.rendered))
        problems += rendered_violations(config, source=args.rendered.name)

    for problem in problems:
        print(f"REFUS — {problem}", file=sys.stderr)
    if problems:
        print(f"{len(problems)} point(s) à corriger, puis relancez ce contrôle.", file=sys.stderr)
        return 1
    print("OK — les réglages sont bons : CoGes peut démarrer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
