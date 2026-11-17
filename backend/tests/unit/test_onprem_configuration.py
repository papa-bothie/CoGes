"""Assemblage « sur site » (ADR 0124) : ce que le dossier deploy/onprem/ garantit.

Tout CoGes sur un PC, base comprise, sur http://localhost. Ces tests lisent les fichiers
versionnés ; le démarrage réel est joué par le workflow « Sur site »
(deploy/onprem-ci/verifier.sh).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
ONPREM = REPO / "deploy" / "onprem"
COMPOSE = ONPREM / "docker-compose.yml"
CADDYFILE = ONPREM / "Caddyfile"
VPS = REPO / "deploy" / "vps"
OWNER_DSN = "COGES_DATABASE_URL_OWNER"

#: Services lancés par `up`, qui tournent en continu.
CONTINUOUS = {"caddy", "autoheal", "postgres", "redis", "front", "api", "worker", "beat", "relay"}
#: Services ponctuels (profil `tools`).
TOOLS = {"migrate", "cli"}


def _compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return data


def _services() -> dict[str, Any]:
    services: dict[str, Any] = _compose()["services"]
    return services


def _image(service: dict[str, Any]) -> str:
    """Nom d'image sans le message d'erreur de `${VAR:?message}`."""
    return re.sub(r":\?[^}]*\}", ":?}", str(service["image"]))


def _megabytes(value: str) -> int:
    match = re.fullmatch(r"(\d+)([mg])b?", value.lower())
    assert match is not None, value
    return int(match.group(1)) * (1024 if match.group(2) == "g" else 1)


# ------------------------------------------------------------------ services


def test_the_stack_is_exactly_the_expected_services() -> None:
    services = _services()
    assert set(services) == CONTINUOUS | TOOLS
    assert "admin" not in services and "cloudflared" not in services
    for name in TOOLS:
        assert services[name].get("profiles") == ["tools"], f"{name} serait lancé par `up`"
    for name in CONTINUOUS:
        assert "profiles" not in services[name], name


@pytest.mark.parametrize("service", sorted(CONTINUOUS | {"cli"}))
def test_no_continuous_service_receives_the_owner_dsn(service: str) -> None:
    """Le DSN de coges_owner vit sur le poste (migrations sur place) : il n'est donné
    qu'au service ponctuel `migrate`, jamais à ce qui tourne en continu ni à `cli`."""
    env = _services()[service].get("environment") or {}
    assert OWNER_DSN not in env
    assert not any("coges_owner" in str(value) for value in env.values())


def test_only_migrate_holds_the_owner_dsn_and_it_migrates() -> None:
    migrate = _services()["migrate"]
    assert (
        "coges_owner:${COGES_OWNER_PASSWORD:?}@postgres:5432/coges"
        in migrate["environment"][OWNER_DSN]
    )
    assert migrate["command"] == ["alembic", "upgrade", "head"]
    assert migrate["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert migrate["restart"] == "no"
    text = COMPOSE.read_text(encoding="utf-8")
    assert len(re.findall(rf"^\s+{OWNER_DSN}:", text, flags=re.M)) == 1


def test_every_dsn_names_its_role_on_the_local_database() -> None:
    expected = {
        "COGES_DATABASE_URL_APP": "coges_app:${COGES_APP_PASSWORD:?}",
        "COGES_DATABASE_URL_RELAY": "coges_relay:${COGES_RELAY_PASSWORD:?}",
        "COGES_DATABASE_URL_ANALYTICS": "coges_analytics:${COGES_ANALYTICS_PASSWORD:?}",
        "COGES_DATABASE_URL_PLATFORM": "coges_app_platform:${COGES_PLATFORM_PASSWORD:?}",
        OWNER_DSN: "coges_owner:${COGES_OWNER_PASSWORD:?}",
    }
    seen: set[str] = set()
    for name, service in _services().items():
        for key, value in (service.get("environment") or {}).items():
            if not key.startswith("COGES_DATABASE_URL"):
                continue
            seen.add(key)
            assert value == f"postgresql+psycopg://{expected[key]}@postgres:5432/coges", (name, key)
            assert "sslmode" not in value
    assert seen == set(expected)


def test_the_application_runs_as_production_without_any_external_service() -> None:
    services = _services()
    for name in ("api", "worker", "beat", "relay", "cli", "migrate"):
        assert services[name]["environment"]["COGES_ENV"] == "production", name
    for name in ("api", "worker", "beat", "relay"):
        env = services[name]["environment"]
        assert env["COGES_DB_POOLER"] == "none"
        assert env["COGES_REDIS_URL"].endswith("@redis:6379/0")
        assert env["COGES_SENTRY_DSN"] == "" and env["COGES_JOB_PING_URLS"] == ""
        for key in env:
            assert not key.startswith(
                ("COGES_SMTP", "COGES_VAPID", "COGES_CLOUDINARY", "COGES_ACCESS")
            )
    api = services["api"]["environment"]
    assert api["COGES_SIGNUP_ENABLED"] == "false"
    assert api["COGES_CORS_ORIGINS"] == "${COGES_PUBLIC_URL:-http://localhost}"
    assert api["COGES_MERCHANT_URL"] == "${COGES_PUBLIC_URL:-http://localhost}"
    assert "COGES_MFA_ENCRYPTION_KEY" in api and "COGES_DATABASE_URL_PLATFORM" in api
    assert "COGES_DATABASE_URL_PLATFORM" in services["worker"]["environment"]
    assert services["front"]["environment"] == {"COGES_API_URL": "http://api:8000"}


def test_the_images_are_the_ones_of_the_vps_compose() -> None:
    """Mêmes images que la production, au même registre : rien n'est construit pour le site."""
    vps = yaml.safe_load((VPS / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    services = _services()
    for name in ("front", "api", "worker", "beat", "relay", "redis", "caddy", "autoheal"):
        assert _image(services[name]) == _image(vps[name]), name
    for name in TOOLS:
        assert _image(services[name]) == _image(vps["worker"])
    assert not any("/admin:" in s["image"] or "/bundle:" in s["image"] for s in services.values())
    assert not any("build" in service for service in services.values())
    # Étiquette obligatoire : pas de défaut, donc jamais `latest` par oubli.
    assert "${COGES_IMAGE_TAG:?" in services["api"]["image"]


def test_postgres_follows_the_production_major_with_a_pinned_minor() -> None:
    """ADR 0095 : la version majeure de la production, lue dans le compose du poste."""
    local = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    major = re.fullmatch(r"postgres:(\d+)-alpine", local["services"]["postgres"]["image"])
    assert major is not None
    postgres = _services()["postgres"]
    assert re.fullmatch(rf"postgres:{major.group(1)}\.\d+-alpine", postgres["image"])
    assert "ports" not in postgres
    assert "pgdata:/var/lib/postgresql" in postgres["volumes"]
    assert "--locale-provider=builtin" in postgres["environment"]["POSTGRES_INITDB_ARGS"]
    assert "--builtin-locale=C.UTF-8" in postgres["environment"]["POSTGRES_INITDB_ARGS"]
    assert "pg_isready -h 127.0.0.1 -U postgres -d coges" in postgres["healthcheck"]["test"][1]


def test_no_password_has_a_default() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "change-me" not in text.lower()
    for variable in re.findall(r"\$\{(COGES_[A-Z_]*(?:PASSWORD|SECRET|KEY))(:?[-?])", text):
        assert variable[1] == ":?", f"{variable[0]} a une valeur par défaut"
    init = (ONPREM / "postgres-init" / "01-roles.sql").read_text(encoding="utf-8")
    assert ":-" not in init and "change-me" not in init.lower()


# ------------------------------------------------------------------ réseau et ports


def test_only_caddy_publishes_a_port_and_only_on_the_loopback() -> None:
    services = _services()
    publishing = {name for name, service in services.items() if service.get("ports")}
    assert publishing == {"caddy"}
    assert services["caddy"]["ports"] == ["127.0.0.1:${COGES_HTTP_PORT:-80}:80"]


def test_no_container_can_reach_the_internet() -> None:
    """Tous les services sont sur un réseau interne ; Caddy seul touche `bord`, le temps
    de publier son port. autoheal n'a aucun réseau."""
    compose = _compose()
    assert compose["networks"]["interne"]["internal"] is True
    for name, service in compose["services"].items():
        if name == "autoheal":
            assert service["network_mode"] == "none"
        elif name == "caddy":
            assert sorted(service["networks"]) == ["bord", "interne"]
        else:
            assert service["networks"] == ["interne"], name


def test_the_api_trusts_forwarded_headers_from_the_internal_subnet_only() -> None:
    compose = _compose()
    subnet = compose["networks"]["interne"]["ipam"]["config"][0]["subnet"]
    api = compose["services"]["api"]["environment"]
    assert api["COGES_FORWARDED_ALLOW_IPS"] == subnet
    assert api["COGES_TRUST_PROXY_HEADERS"] == "true"
    # Distinct des sous-réseaux du VPS (coges_edge et coges_tunnel).
    assert not subnet.startswith("172.30.")


# ------------------------------------------------------------------ réglages éprouvés du VPS


def test_the_memory_caps_fit_under_three_gigabytes() -> None:
    """Docker Desktop ne donne que la moitié des 8 Go : tout doit tenir sous 3 Go."""
    services = _services()
    total = sum(_megabytes(services[name]["mem_limit"]) for name in CONTINUOUS)
    assert total < 3 * 1024, total
    announced = re.search(r"totalisent ([\d ]+) Mo", COMPOSE.read_text(encoding="utf-8"))
    assert announced is not None and int(announced.group(1).replace(" ", "")) == total
    for name in TOOLS:
        assert "mem_limit" in services[name]


def test_redis_keeps_the_queue_and_leaves_room_for_the_aof_rewrite() -> None:
    redis = _services()["redis"]
    command = " ".join(redis["command"])
    assert "--maxmemory-policy noeviction" in command and "--appendonly yes" in command
    for renamed in ("FLUSHALL", "FLUSHDB", "CONFIG", "DEBUG", "SHUTDOWN", "MODULE"):
        assert f'--rename-command {renamed} ""' in command
    maxmemory = re.search(r"--maxmemory (\d+mb)", command)
    assert maxmemory is not None
    assert _megabytes(maxmemory.group(1)) <= _megabytes(redis["mem_limit"]) * 0.6


def test_the_proven_settings_of_the_vps_are_kept() -> None:
    services = _services()
    for name in CONTINUOUS:
        service = services[name]
        assert service["restart"] == "unless-stopped", name
        assert service["logging"]["options"]["max-size"] == "10m", name
        if name != "autoheal":
            assert service["security_opt"] == ["no-new-privileges:true"], name
            assert service["labels"] == {"autoheal": "true"}, name
            assert "healthcheck" in service, name
    for name in ("worker", "beat", "relay"):
        assert services[name]["stop_grace_period"] == "120s"
    assert re.search(r"@sha256:[0-9a-f]{64}$", services["autoheal"]["image"])
    assert "--concurrency=1" in services["worker"]["command"]


# ------------------------------------------------------------------ Caddyfile


def test_caddy_serves_one_plain_http_site_and_never_asks_for_a_certificate() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    sites = [
        line.removesuffix("{").strip()
        for line in text.splitlines()
        if line.endswith("{") and not line.startswith(("\t", " ", "#", "("))
    ]
    assert sites == ["", "http://localhost"]  # le bloc global, puis le seul site
    assert re.search(r"^\tauto_https off$", text, flags=re.M)
    assert "email" not in text and "acme" not in text.lower()
    assert "{$" not in text, "aucune variable : le fichier se lit tel quel"


def test_caddy_routes_like_the_vps_without_the_platform_administration() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    platform = text.index("handle /api/v1/platform/* {")
    api = text.index("handle /api/v1/* {")
    assert platform < api
    assert re.search(r"handle /api/v1/platform/\* \{\s+respond 404\s+\}", text)
    assert "reverse_proxy api:8000" in text and "reverse_proxy front:3000" in text


def test_caddy_keeps_the_vps_headers_except_hsts() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    vps = (VPS / "Caddyfile").read_text(encoding="utf-8")
    for header in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
        line = re.search(rf"^\s+{header} .*$", vps, flags=re.M)
        assert line is not None and line.group(0).strip() in text, header
    assert 'Permissions-Policy "camera=(self), microphone=(), geolocation=()"' in text
    assert "-Server" in text and "-Via" in text
    # Ni posé par Caddy, ni laissé passer quand l'API l'envoie (COGES_ENV=production).
    assert re.search(r"^\s+-Strict-Transport-Security$", text, flags=re.M)
    assert not re.search(r"^\s+Strict-Transport-Security", text, flags=re.M)


def test_caddy_keeps_the_log_filter_the_body_limit_and_the_maintenance_page() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    vps = (VPS / "Caddyfile").read_text(encoding="utf-8")
    for line in (
        'request>uri regexp "\\?.*$" ""',
        "request>headers>Cookie delete",
        "request>headers>Authorization delete",
        "request>headers>Idempotency-Key delete",
        "resp_headers>Set-Cookie delete",
        "max_size 25MB",
        "handle_errors 502 503 504 {",
        "rewrite * /maintenance.html",
    ):
        assert line in vps, f"le Caddyfile du VPS a changé : {line}"
        assert line in text, line


# ------------------------------------------------------------------ dossier autonome


def test_the_maintenance_page_is_the_one_of_the_vps() -> None:
    assert (ONPREM / "maintenance.html").read_bytes() == (VPS / "maintenance.html").read_bytes()


def test_the_folder_references_nothing_outside_itself() -> None:
    """Le lot 5 publiera deploy/onprem/ tel quel : rien n'y pointe vers le reste du dépôt."""
    for name, service in _services().items():
        for volume in service.get("volumes") or []:
            source = str(volume).split(":", 1)[0]
            if source.startswith("."):
                assert source.startswith("./") and ".." not in source, (name, volume)
                assert (ONPREM / source).exists(), (name, volume)
            elif source.startswith("/"):
                assert source == "/var/run/docker.sock", (name, volume)
    for path in ONPREM.rglob("*"):
        if path.is_file() and path.suffix != ".pyc":
            assert "../" not in path.read_text(encoding="utf-8"), path
    for script in ONPREM.glob("*.py"):
        imports = re.findall(r"^(?:from|import) ([\w.]+)", script.read_text("utf-8"), flags=re.M)
        assert not any(name.startswith(("app", "check_runtime_env")) for name in imports), script


def test_the_vps_bundle_carries_nothing_from_the_on_site_folder() -> None:
    bundle = (VPS / "Dockerfile.bundle").read_text(encoding="utf-8")
    assert "onprem" not in bundle
    for name in ("backend", "frontend", "frontend-admin"):
        ignored = REPO / name / ".dockerignore"
        assert "onprem" not in ignored.read_text(encoding="utf-8")


def test_every_file_of_the_folder_ends_its_lines_with_lf() -> None:
    """Un script ou un fichier de réglages en CRLF, extrait sous Windows, casse le
    conteneur qui le lit : `.gitattributes` l'impose, dans ce dossier seulement."""
    attributes = (ONPREM / ".gitattributes").read_text(encoding="utf-8")
    assert re.search(r"^\* text=auto eol=lf$", attributes, flags=re.M)
    assert not (REPO / ".gitattributes").exists() or "onprem" not in (
        REPO / ".gitattributes"
    ).read_text(encoding="utf-8")
    files = [path for path in ONPREM.rglob("*") if path.is_file() and path.suffix != ".pyc"]
    assert len(files) >= 8
    for path in files:
        assert b"\r" not in path.read_bytes(), f"{path} contient un retour chariot"


# ------------------------------------------------------------------ rôles PostgreSQL

_ROLE = re.compile(r"^CREATE ROLE (\w+)\s+(.*?);", flags=re.M | re.S)


def _roles(path: Path) -> dict[str, frozenset[str]]:
    """Rôles et attributs d'un script d'amorçage, mot de passe mis à part."""
    text = re.sub(r"--.*$", "", path.read_text(encoding="utf-8"), flags=re.M)
    roles: dict[str, frozenset[str]] = {}
    for name, attributes in _ROLE.findall(text):
        attributes = re.sub(r"PASSWORD\s+(:?'[^']*'|\S+)", "", attributes)
        attributes = re.sub(r"CONNECTION LIMIT (\d+)", r"CONNECTION_LIMIT_\1", attributes)
        roles[name] = frozenset(attributes.split())
    return roles


def _statements(path: Path, pattern: str) -> set[str]:
    text = re.sub(r"--.*$", "", path.read_text(encoding="utf-8"), flags=re.M)
    return {re.sub(r"\s+", " ", match) for match in re.findall(pattern, text, flags=re.M)}


def test_the_roles_are_those_of_the_reference_script() -> None:
    """Les mêmes rôles et les mêmes attributs que deploy/postgres/init/01-roles.sql : si
    l'un des deux scripts change sans l'autre, ce test échoue."""
    reference = REPO / "deploy" / "postgres" / "init" / "01-roles.sql"
    onprem = ONPREM / "postgres-init" / "01-roles.sql"
    assert _roles(onprem) == _roles(reference)
    assert len(_roles(onprem)) >= 11
    for pattern in (r"^GRANT coges_\w+\s+TO \w+ WITH INHERIT FALSE;", r"^ALTER ROLE .*;"):
        assert _statements(onprem, pattern) == _statements(reference, pattern), pattern


def test_the_only_database_is_coges_with_the_reference_grants() -> None:
    reference = (REPO / "deploy" / "postgres" / "init" / "01-roles.sql").read_text("utf-8")
    onprem = (ONPREM / "postgres-init" / "01-roles.sql").read_text(encoding="utf-8")
    assert re.findall(r"^CREATE DATABASE (\w+)", onprem, flags=re.M) == ["coges"]
    assert re.findall(r"^\\connect (\w+)", onprem, flags=re.M) == ["coges"]
    # Les GRANT de la base `coges` du script de référence, à l'identique.
    block = reference.split("\\connect coges\n", 1)[1].split("\\connect", 1)[0].strip()
    assert block in onprem
    assert "\\set ON_ERROR_STOP on" in onprem


# ------------------------------------------------------------------ modèle de réglages


def test_the_model_asks_for_every_variable_the_compose_requires() -> None:
    model = (ONPREM / "coges.env.example").read_text(encoding="utf-8")
    keys = set(re.findall(r"^([A-Z_]+)=", model, flags=re.M))
    required = set(re.findall(r"\$\{(COGES_[A-Z_]+):\?", COMPOSE.read_text(encoding="utf-8")))
    assert required <= keys, required - keys
    # Valeurs vides : aucun secret dans le modèle.
    for key in required:
        assert re.search(rf"^{key}=$", model, flags=re.M), f"{key} a une valeur dans le modèle"
    assert "À REMPLIR" in model and "NE PAS TOUCHER" in model
    assert "DATABASE_URL" not in model and "REDIS_URL" not in model
