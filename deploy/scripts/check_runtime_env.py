"""Garde-fou 2 de l'ADR 0042 : le DSN de `coges_owner` n'existe que dans le job de migration.

Échoue (code 1) si l'on trouve, dans un environnement d'**exécution** :

* une variable `COGES_DATABASE_URL_OWNER` (ou sa jumelle de test) ;
* une valeur quelconque qui désigne l'utilisateur `coges_owner` dans un DSN.

Sources contrôlées :

1. les fichiers compose versionnés (`--compose`, répétable ; par défaut celui du VPS et
   celui des workers du poste), lus tels quels ;
2. avec `--require-vps` et `--env-file`, le fichier de secrets d'une pile du VPS
   (`/etc/coges/coges.env`, ADR 0083). Il doit en plus : désigner Neon en
   `sslmode=require` pour chaque DSN, garder Redis sur le réseau interne (aucune URL
   Redis vers l'extérieur), donner un domaine public servi en HTTPS (nom d'hôte nu,
   jamais `http://`), des secrets assez longs (JWT et Redis, 32 caractères au moins) et
   une administration protégée (double authentification, Cloudflare Access, liste
   d'adresses ou secours SSH, ADR 0104 et 0105) avec la clé COGES_MFA_ENCRYPTION_KEY.

`deploy.sh` le lance avant chaque démarrage sur le VPS ; la CI, sur les fichiers versionnés.

Usage : python deploy/scripts/check_runtime_env.py [--compose FICHIER]…
        [--require-vps --env-file FICHIER]
Bibliothèque standard seulement : le script tourne avant toute installation.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import re
import sys
import ipaddress
import urllib.parse
from collections.abc import Iterable
from pathlib import Path

FORBIDDEN_KEYS = frozenset({"COGES_DATABASE_URL_OWNER", "COGES_TEST_DATABASE_URL_OWNER"})
#: `postgresql+psycopg://coges_owner:…@` — l'utilisateur d'un DSN, quel que soit le schéma.
OWNER_IN_DSN = re.compile(r"://coges_owner(?::|@)")
#: Le rôle de sauvegarde (ADR 0084) lit tout malgré la RLS : jamais à l'exécution.
BACKUP_IN_DSN = re.compile(r"://coges_backup(?::|@)")
#: DSN d'exécution attendus sur le VPS, et le seul rôle que chacun peut désigner : une
#: liste blanche, pas une liste noire (ADR 0088) — « neondb_owner », « coges%5Fowner »
#: ou `?user=` passaient l'ancien contrôle.
RUNTIME_DSNS: dict[str, str] = {
    "COGES_DATABASE_URL_APP": "coges_app",
    "COGES_DATABASE_URL_RELAY": "coges_relay",
    "COGES_DATABASE_URL_ANALYTICS": "coges_analytics",
    # Administration de la plateforme (ADR 0089) : métadonnées seulement.
    "COGES_DATABASE_URL_PLATFORM": "coges_app_platform",
}
#: Rôles qu'un environnement d'exécution peut désigner, quelle que soit la variable.
RUNTIME_ROLES = frozenset(RUNTIME_DSNS.values())
#: Nom d'hôte nu : `app.exemple.sn`, sans schéma, port ni chemin.
HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
#: Hôtes Redis du réseau Docker interne.
INTERNAL_REDIS_HOSTS = frozenset({"redis"})
MIN_SECRET_LENGTH = 32
#: Porte de l'administration (ADR 0104, 0105).
ADMIN_GATES = frozenset({"mfa", "cloudflare", "ip", "ssh"})
#: La version de ce bundle impose la double authentification à tout compte de la
#: plateforme : une constante du code, comme `app.core.mfa.PLATFORM_MFA_REQUIRED` (test de
#: concordance), jamais une variable qu'on pourrait éteindre. Un bundle plus ancien ne
#: connaît pas la porte `mfa` et la refuse : impossible d'ouvrir l'administration sans
#: filtre avec une version qui ne demande pas de code.
PLATFORM_MFA_REQUIRED = True
ACCESS_TEAM_DOMAIN = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com")
ACCESS_AUD = re.compile(r"[0-9a-f]{64}")
#: Le jeton d'un tunnel est du JSON en base64 (compte, tunnel, secret) : bien plus long.
TUNNEL_TOKEN = re.compile(r"[A-Za-z0-9+/=_-]+")
MIN_TUNNEL_TOKEN_LENGTH = 100

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSES = (
    REPO_ROOT / "deploy" / "vps" / "docker-compose.yml",
    REPO_ROOT / "deploy" / "docker-compose.worker.yml",
)


def dsn_users(value: str) -> list[str]:
    """Utilisateurs que désigne un DSN, **décodés** : avant « @ » et en `?user=`."""
    if "://" not in value:
        return []
    parsed = urllib.parse.urlsplit(value)
    users = [urllib.parse.unquote(parsed.username)] if parsed.username else []
    users += urllib.parse.parse_qs(parsed.query).get("user", [])
    return users


def violations(pairs: Iterable[tuple[str, str]], *, source: str) -> list[str]:
    """Variables interdites parmi des couples (nom, valeur)."""
    found: list[str] = []
    for key, value in pairs:
        users = dsn_users(value or "")
        decoded = urllib.parse.unquote(value or "")
        if key in FORBIDDEN_KEYS:
            found.append(f"{source} : la variable {key} ne doit pas exister à l'exécution")
        elif "coges_owner" in users or OWNER_IN_DSN.search(decoded):
            found.append(f"{source} : {key} désigne l'utilisateur coges_owner")
        elif "coges_backup" in users or BACKUP_IN_DSN.search(decoded):
            found.append(f"{source} : {key} désigne l'utilisateur coges_backup")
        elif any(user not in RUNTIME_ROLES for user in users) and key.startswith("COGES_DATABASE"):
            strangers = ", ".join(user for user in users if user not in RUNTIME_ROLES)
            found.append(f"{source} : {key} désigne {strangers}, hors des rôles d'exécution")
    return found


def compose_violations(text: str, *, source: str) -> list[str]:
    """Le fichier compose est lu comme du texte : toute mention suffit à refuser."""
    found = [f"{source} : mention de {key}" for key in sorted(FORBIDDEN_KEYS) if key in text]
    # Décodé d'abord : « coges%5Fowner » est coges_owner (ADR 0088).
    text = urllib.parse.unquote(text)
    if OWNER_IN_DSN.search(text) or re.search(r"[?&]user=coges_owner\b", text):
        found.append(f"{source} : un DSN désigne l'utilisateur coges_owner")
    if BACKUP_IN_DSN.search(text):
        found.append(f"{source} : un DSN désigne l'utilisateur coges_backup")
    return found


def read_env_file(text: str) -> list[tuple[str, str]]:
    """Couples (nom, valeur) d'un fichier `NOM=valeur`, sans rien exécuter."""
    pairs: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        pairs.append((key.strip(), value))
    return pairs


def _allowed_ips_violations(entries: list[str], *, source: str) -> list[str]:
    """Une entrée illisible, Caddy refuserait de démarrer ; `0.0.0.0/0` ouvrirait à tous."""
    found: list[str] = []
    for entry in entries:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            found.append(f"{source} : COGES_ADMIN_ALLOWED_IPS contient « {entry} », illisible")
            continue
        if network.prefixlen == 0:
            found.append(f"{source} : COGES_ADMIN_ALLOWED_IPS ouvre l'administration à tous")
    return found


def admin_gate_violations(values: dict[str, str], *, source: str) -> list[str]:
    """La porte de l'administration (ADR 0104) : jamais une admin sans protection.

    * `cloudflare` : Cloudflare Access par le tunnel, configuration complète ; les adresses
      deviennent un filet facultatif ;
    * `ip` (aussi quand la variable manque, fichiers d'avant ce lot) : liste d'adresses
      obligatoire, comme à l'ADR 0089 ;
    * `ssh` : secours, servi sur le seul port local du VPS (tunnel SSH) ;
    * `mfa` (ADR 0105) : 443 sans filtre d'adresse ; la double authentification
      obligatoire de cette version est la barrière (et sa clé, contrôlée à part).
    Hors `cloudflare`, les variables d'Access doivent être vides : l'API exigerait un
    jeton que plus rien n'apporte, et l'administration resterait fermée.
    """
    found: list[str] = []
    gate = values.get("COGES_ADMIN_GATE", "ip")
    allowed = values.get("COGES_ADMIN_ALLOWED_IPS", "").split()
    if gate not in ADMIN_GATES:
        return [f"{source} : COGES_ADMIN_GATE vaut « {gate} » (mfa, cloudflare, ip ou ssh)"]
    if gate == "mfa" and not PLATFORM_MFA_REQUIRED:
        return [
            f"{source} : COGES_ADMIN_GATE=mfa exige une version qui impose la double "
            "authentification de l'administration"
        ]

    if gate == "cloudflare":
        team = values.get("COGES_ACCESS_TEAM_DOMAIN", "")
        if not ACCESS_TEAM_DOMAIN.fullmatch(team):
            found.append(
                f"{source} : COGES_ACCESS_TEAM_DOMAIN doit être <équipe>.cloudflareaccess.com"
            )
        if not ACCESS_AUD.fullmatch(values.get("COGES_ACCESS_AUD", "")):
            found.append(f"{source} : COGES_ACCESS_AUD compte 64 caractères hexadécimaux")
        tunnel = values.get("COGES_CLOUDFLARE_TUNNEL_TOKEN", "")
        if len(tunnel) < MIN_TUNNEL_TOKEN_LENGTH or not TUNNEL_TOKEN.fullmatch(tunnel):
            found.append(
                f"{source} : COGES_CLOUDFLARE_TUNNEL_TOKEN manque ou ne ressemble pas au jeton "
                "du tunnel (tableau de bord Zero Trust)"
            )
    else:
        for key in ("COGES_ACCESS_TEAM_DOMAIN", "COGES_ACCESS_AUD"):
            if values.get(key):
                found.append(
                    f"{source} : COGES_ADMIN_GATE={gate} : videz {key} (l'API exigerait "
                    "un jeton Cloudflare qui n'arrive plus)"
                )
        if gate == "ip" and not allowed:
            found.append(f"{source} : COGES_ADMIN_ALLOWED_IPS est vide")

    if gate != "ssh":
        found += _allowed_ips_violations(allowed, source=source)
    return found


def mfa_key_violations(values: dict[str, str], *, source: str) -> list[str]:
    """COGES_MFA_ENCRYPTION_KEY (ADR 0105) : 32 octets en base64url. Sans elle, l'API
    refuse de démarrer (l'administration exige la double authentification)."""
    value = values.get("COGES_MFA_ENCRYPTION_KEY", "").strip("\"'")
    if not value:
        return [
            f"{source} : COGES_MFA_ENCRYPTION_KEY est vide "
            "(openssl rand -base64 32 | tr '+/' '-_', à garder comme la clé age)"
        ]
    try:
        key = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error):
        key = b""
    if len(key) != 32 or base64.urlsafe_b64encode(key).decode().rstrip("=") != value.rstrip("="):
        return [f"{source} : COGES_MFA_ENCRYPTION_KEY doit faire 32 octets en base64url"]
    return []


def vps_violations(
    pairs: list[tuple[str, str]], *, source: str, stack: str | None = None
) -> list[str]:
    """Règles propres au VPS (ADR 0083), en plus du garde-fou sur le propriétaire."""
    values = dict(pairs)
    found = violations(pairs, source=source)

    # Une préproduction copiée du modèle de production prendrait ses alias réseau sur
    # `coges_edge` (ADR 0088) : la pile annoncée doit être celle qu'on démarre.
    declared = values.get("COGES_STACK")
    if stack is not None and declared is not None and declared != stack:
        found.append(f"{source} : COGES_STACK vaut « {declared} » pour la pile « {stack} »")

    for key, role in RUNTIME_DSNS.items():
        dsn = values.get(key, "")
        if not dsn:
            found.append(f"{source} : {key} est vide")
            continue
        users = dsn_users(dsn)
        if users != [role]:
            found.append(
                f"{source} : {key} doit se connecter sous {role} (lu : {users or 'aucun'})"
            )
        parsed = urllib.parse.urlsplit(dsn)
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("sslmode") != ["require"] and query.get("sslmode") != ["verify-full"]:
            found.append(f"{source} : {key} doit imposer sslmode=require (Neon)")
        if parsed.hostname in {None, "localhost", "127.0.0.1", "postgres"}:
            found.append(f"{source} : {key} doit viser Neon, pas une base locale")

    redis_url = values.get("COGES_REDIS_URL", "")
    if redis_url and urllib.parse.urlsplit(redis_url).hostname not in INTERNAL_REDIS_HOSTS:
        found.append(f"{source} : COGES_REDIS_URL doit rester sur le Redis interne du VPS")

    domain = values.get("COGES_DOMAIN", "")
    if "://" in domain:
        found.append(f"{source} : COGES_DOMAIN est un nom d'hôte nu (HTTPS imposé par Caddy)")
    elif not HOSTNAME.match(domain):
        found.append(f"{source} : COGES_DOMAIN invalide ou vide")

    # Seule la production sert l'administration : la préprod n'en a pas besoin.
    if (declared or stack) != "preprod":
        found += admin_gate_violations(values, source=source)

    found += mfa_key_violations(values, source=source)

    for key in ("COGES_JWT_SECRET", "COGES_REDIS_PASSWORD"):
        if len(values.get(key, "")) < MIN_SECRET_LENGTH:
            found.append(f"{source} : {key} doit compter {MIN_SECRET_LENGTH} caractères au moins")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--compose", type=Path, action="append")
    parser.add_argument(
        "--require-vps",
        action="store_true",
        help="Contrôler aussi le fichier de secrets d'une pile du VPS (--env-file)",
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--stack", help="pile démarrée (production, preprod) : COGES_STACK doit concorder"
    )
    args = parser.parse_args(argv)

    problems: list[str] = []
    for compose in args.compose or DEFAULT_COMPOSES:
        problems += compose_violations(compose.read_text(encoding="utf-8"), source=str(compose))

    if args.require_vps:
        if args.env_file is None:
            problems.append("--require-vps exige --env-file (fichier de secrets de la pile)")
        else:
            pairs = read_env_file(args.env_file.read_text(encoding="utf-8"))
            problems += vps_violations(pairs, source=str(args.env_file), stack=args.stack)
    elif args.env_file is not None:
        pairs = read_env_file(args.env_file.read_text(encoding="utf-8"))
        problems += violations(pairs, source=str(args.env_file))

    for problem in problems:
        print(f"REFUS — {problem}", file=sys.stderr)
    if not problems:
        print("OK — aucun DSN propriétaire dans les environnements d'exécution.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
