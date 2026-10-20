"""Configuration du VPS : journaux, mémoire de Redis, images figées (P2.21, ADR 0088).

* Caddy journalisait l'URL complète, chaîne de requête comprise : les recherches
  (`?search=Awa Ndiaye`, un téléphone) finissaient dans les journaux.
* Redis réécrit son AOF par un `fork` : la copie sur écriture peut presque doubler la
  mémoire. Avec `maxmemory` à 512 Mo sous une limite de 640 Mo, la réécriture faisait
  tuer le conteneur.
* `autoheal` lit le socket Docker : une étiquette déplacée par son éditeur lui donnerait
  un autre code avec la main sur toute la machine. Figée par condensat.
* Le contexte de l'image du front ne doit emporter ni `.env.local` ni jeton.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
CADDYFILE = REPO / "deploy" / "vps" / "Caddyfile"
COMPOSE = REPO / "deploy" / "vps" / "docker-compose.yml"


def _megabytes(value: str) -> int:
    number, unit = re.fullmatch(r"(\d+)([mg]b?)", value.lower()).groups()  # type: ignore[union-attr]
    return int(number) * (1024 if unit.startswith("g") else 1)


def test_caddy_never_logs_the_query_string() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    assert re.search(r"request>uri\s+regexp", text), "la chaîne de requête part dans les journaux"


def test_redis_leaves_room_for_the_aof_rewrite() -> None:
    service = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["redis"]
    command = " ".join(service["command"])
    default = re.search(r"--maxmemory \$\{COGES_REDIS_MAXMEMORY:-(\w+)\}", command)
    assert default is not None
    assert _megabytes(default.group(1)) <= _megabytes(service["mem_limit"]) * 0.6


def test_autoheal_is_pinned_by_digest() -> None:
    image = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["autoheal"]["image"]
    assert re.search(r"@sha256:[0-9a-f]{64}$", image), image


def test_the_front_build_context_carries_no_local_secret() -> None:
    ignored = (REPO / "frontend" / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env*" in ignored
