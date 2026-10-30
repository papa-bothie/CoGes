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

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
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


# ------------------------------------------- porte de l'administration (ADR 0104)

VPS = REPO / "deploy" / "vps"
CADDY_IMAGE = "caddy:2.10.2-alpine"


def _services() -> dict[str, Any]:
    services: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    return services


def _site_addresses(path: Path) -> list[str]:
    """Adresses de site d'un fichier Caddy : lignes de premier niveau ouvrant un bloc."""
    return [
        line.removesuffix("{").strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.endswith("{") and not line.startswith(("\t", " ", "#", "("))
    ]


def test_each_gate_has_its_file_and_the_bundle_carries_them() -> None:
    caddyfile = CADDYFILE.read_text(encoding="utf-8")
    bundle = (VPS / "Dockerfile.bundle").read_text(encoding="utf-8")
    volumes = _services()["caddy"]["volumes"]
    assert "import admin-{$COGES_ADMIN_GATE:ip}.caddy" in caddyfile
    for gate in ("mfa", "cloudflare", "ip", "ssh"):
        assert (VPS / f"admin-{gate}.caddy").is_file()
        assert f"deploy/vps/admin-{gate}.caddy" in bundle
        assert f"./admin-{gate}.caddy:/etc/caddy/admin-{gate}.caddy:ro" in volumes
    assert "admin." not in "".join(_site_addresses(CADDYFILE)), "admin servi hors de sa porte"


def test_behind_cloudflare_the_admin_is_on_the_internal_port_only() -> None:
    assert _site_addresses(VPS / "admin-cloudflare.caddy") == ["http://:8081"]
    assert _site_addresses(VPS / "admin-ssh.caddy") == ["http://:8082"]
    assert _site_addresses(VPS / "admin-ip.caddy") == ["admin.{$COGES_DOMAIN}"]
    assert _site_addresses(VPS / "admin-mfa.caddy") == ["admin.{$COGES_DOMAIN}"]
    ports = _services()["caddy"]["ports"]
    assert not any("8081" in port for port in ports), ports
    assert [port for port in ports if "8082" in port] == ["127.0.0.1:8082:8082"]


def test_the_pages_are_checked_by_the_api_before_being_served() -> None:
    text = (VPS / "admin-cloudflare.caddy").read_text(encoding="utf-8")
    assert re.search(
        r"forward_auth production-api:8000 \{\s*uri /api/v1/platform/access\s*\}", text
    )


def test_only_cloudflared_and_caddy_share_the_tunnel_network() -> None:
    """Caddy croit CF-Connecting-IP venu de ce sous-réseau : personne d'autre n'y est."""
    services = _services()
    members = sorted(
        name for name, service in services.items() if "tunnel" in service.get("networks", [])
    )
    assert members == ["caddy", "cloudflared"]
    network = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["networks"]["tunnel"]
    subnet = network["ipam"]["config"][0]["subnet"]
    assert f"trusted_proxies static {subnet}" in CADDYFILE.read_text(encoding="utf-8")


def test_the_tunnel_is_pinned_and_holds_its_token_alone() -> None:
    services = _services()
    cloudflared = services["cloudflared"]
    assert re.search(r"@sha256:[0-9a-f]{64}$", cloudflared["image"]), cloudflared["image"]
    assert cloudflared["profiles"] == ["tunnel"]
    assert "ports" not in cloudflared
    assert cloudflared["environment"]["TUNNEL_TOKEN"] == "${COGES_CLOUDFLARE_TUNNEL_TOKEN:-}"
    holders = [
        name
        for name, service in services.items()
        if "COGES_CLOUDFLARE_TUNNEL_TOKEN" in str(service)
    ]
    assert holders == ["cloudflared"]
    api = services["api"]["environment"]
    assert api["COGES_ACCESS_TEAM_DOMAIN"] == "${COGES_ACCESS_TEAM_DOMAIN:-}"
    assert api["COGES_ACCESS_AUD"] == "${COGES_ACCESS_AUD:-}"


def _adapt(gate: str, allowed_ips: str) -> dict[str, Any]:
    tunnel_ips = allowed_ips or "0.0.0.0/0 ::/0"
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-e", "COGES_DOMAIN=coges.example.sn",
            "-e", "COGES_ACME_EMAIL=ops@example.sn",
            "-e", f"COGES_ADMIN_GATE={gate}",
            "-e", f"COGES_ADMIN_ALLOWED_IPS={allowed_ips}",
            "-e", f"COGES_ADMIN_TUNNEL_IPS={tunnel_ips}",
            "-v", f"{VPS}:/etc/caddy:ro",
            CADDY_IMAGE, "caddy", "adapt", "--config", "/etc/caddy/Caddyfile",
            "--adapter", "caddyfile",
        ],
        capture_output=True, text=True, timeout=180, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    config: dict[str, Any] = json.loads(result.stdout)
    return config


def _listeners(config: dict[str, Any]) -> dict[str, list[str]]:
    """Port écouté → noms d'hôte servis."""
    return {
        ",".join(server["listen"]): sorted(
            host
            for route in server.get("routes", [])
            for match in route.get("match", [])
            for host in match.get("host", [])
        )
        for server in config["apps"]["http"]["servers"].values()
    }


needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker absent")


@needs_docker
@pytest.mark.parametrize(
    ("gate", "allowed_ips", "expected"),
    [
        (
            "cloudflare",
            "",
            {":443": ["coges.example.sn", "preprod.coges.example.sn"], ":8081": []},
        ),
        (
            "ip",
            "192.0.2.10",
            {
                ":443": [
                    "admin.coges.example.sn",
                    "coges.example.sn",
                    "preprod.coges.example.sn",
                ]
            },
        ),
        ("ssh", "", {":443": ["coges.example.sn", "preprod.coges.example.sn"], ":8082": []}),
        (
            "mfa",
            "",
            {
                ":443": [
                    "admin.coges.example.sn",
                    "coges.example.sn",
                    "preprod.coges.example.sn",
                ]
            },
        ),
    ],
)
def test_the_rendered_caddyfile_serves_the_admin_only_through_its_gate(
    gate: str, allowed_ips: str, expected: dict[str, list[str]]
) -> None:
    assert _listeners(_adapt(gate, allowed_ips)) == expected


@needs_docker
def test_behind_the_tunnel_an_empty_allow_list_lets_access_decide() -> None:
    """Vide, le filet laisse tout passer à l'étape d'Access ; posé, il filtre l'adresse
    réelle du client."""
    open_ranges = re.findall(
        r'"client_ip": \{"ranges": (\[[^\]]*\])', json.dumps(_adapt("cloudflare", ""))
    )
    assert open_ranges == ['["0.0.0.0/0", "::/0"]']
    narrow = json.dumps(_adapt("cloudflare", "196.207.1.10"))
    assert '"client_ip": {"ranges": ["196.207.1.10"]}' in narrow


def _admin_routes(config: dict[str, Any]) -> list[Any]:
    return [
        route
        for server in config["apps"]["http"]["servers"].values()
        for route in server.get("routes", [])
        if "admin.coges.example.sn" in json.dumps(route.get("match", []))
    ]


@needs_docker
def test_the_mfa_gate_filters_no_address_but_keeps_the_headers_and_the_body_limit() -> None:
    """Porte `mfa` (ADR 0105) : 443 public, sans `remote_ip` ; mêmes en-têtes de sécurité,
    même plafond de corps (1 Mo) et routes commerçantes fermées que le mode `ip`."""
    routes = json.dumps(_admin_routes(_adapt("mfa", "")))
    assert "remote_ip" not in routes and "client_ip" not in routes
    assert "Strict-Transport-Security" in routes and "X-Frame-Options" in routes
    assert '"max_size": 1000000' in routes
    assert '"status_code": 404' in routes
    assert "production-api:8000" in routes and "production-admin:3000" in routes
    # Le mode `ip` garde, lui, son filtre.
    assert "remote_ip" in json.dumps(_admin_routes(_adapt("ip", "192.0.2.10")))
