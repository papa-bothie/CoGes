"""Contrôles de l'installation sur site (ADR 0124) : réglages et chemins protégés."""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
ONPREM = REPO / "deploy" / "onprem"


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load(ONPREM / "check_onprem_env.py")
paths = _load(ONPREM / "check_protected_paths.py")

MFA_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")


def _values(**changes: str | None) -> dict[str, str]:
    """Le modèle rempli correctement, puis les changements du cas testé (None : retiré)."""
    values = {
        "COGES_IMAGE_TAG": "v1.4.0",
        "COGES_IMAGE_REGISTRY": "ghcr.io/papa-bothie/coges",
        "COGES_HTTP_PORT": "80",
        "COGES_PUBLIC_URL": "http://localhost",
        "COGES_MFA_ENCRYPTION_KEY": MFA_KEY,
    }
    for index, key in enumerate(check.SECRETS):
        values[key] = f"{index:x}" * 64
    for key, value in changes.items():
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
    return values


def _text(**changes: str | None) -> str:
    return "".join(f"{key}={value}\n" for key, value in _values(**changes).items())


def _refusals(**changes: str | None) -> list[str]:
    found: list[str] = check.env_file_violations(_text(**changes), source="coges.env")
    return found


# ------------------------------------------------------------------ le fichier de réglages


def test_the_model_filled_correctly_passes(tmp_path: Path) -> None:
    assert _refusals() == []
    env_file = tmp_path / "coges.env"
    env_file.write_text(_text(), encoding="utf-8", newline="\n")
    assert check.main(["--env-file", str(env_file)]) == 0


def test_the_empty_model_is_refused_line_by_line() -> None:
    model = (ONPREM / "coges.env.example").read_text(encoding="utf-8")
    refusals = check.env_file_violations(model, source="coges.env")
    for key in (*check.SECRETS, "COGES_MFA_ENCRYPTION_KEY", "COGES_IMAGE_TAG"):
        assert any(f"{key} est vide" in refusal for refusal in refusals), key


def test_a_short_secret_is_refused() -> None:
    refusals = _refusals(COGES_JWT_SECRET="ab" * 8)
    assert refusals == ["coges.env : COGES_JWT_SECRET compte 16 caractères, il en faut 32 au moins"]


@pytest.mark.parametrize("value", ["change-me-" + "0" * 32, "CHANGE-ME-PLATFORM" + "0" * 32])
def test_a_secret_left_at_a_model_value_is_refused(value: str) -> None:
    refusals = _refusals(COGES_APP_PASSWORD=value)
    assert refusals == [
        "coges.env : COGES_APP_PASSWORD garde une valeur de modèle : tirez un vrai mot de passe"
    ]


def test_a_secret_that_is_not_hexadecimal_is_refused() -> None:
    refusals = _refusals(COGES_REDIS_PASSWORD="motdepasse$avec#signes" + "x" * 20)
    assert len(refusals) == 1 and "hexadécimal" in refusals[0]


def test_two_identical_secrets_are_refused() -> None:
    refusals = _refusals(COGES_RELAY_PASSWORD="0" * 64)  # celui de COGES_POSTGRES_PASSWORD
    assert refusals == [
        "coges.env : deux mots de passe sont identiques : tirez-en un différent pour chacun"
    ]


@pytest.mark.parametrize("value", ["", "trop-court", "A" * 43])
def test_the_mfa_key_must_be_32_random_bytes(value: str) -> None:
    refusals = _refusals(COGES_MFA_ENCRYPTION_KEY=value)
    assert len(refusals) == 1 and "COGES_MFA_ENCRYPTION_KEY" in refusals[0]


@pytest.mark.parametrize("tag", ["", "latest", "LATEST"])
def test_an_empty_or_latest_image_tag_is_refused(tag: str) -> None:
    refusals = _refusals(COGES_IMAGE_TAG=tag)
    assert len(refusals) == 1 and "COGES_IMAGE_TAG" in refusals[0]


@pytest.mark.parametrize("env", ["local", "staging", "ci"])
def test_any_environment_but_production_is_refused(env: str) -> None:
    refusals = _refusals(COGES_ENV=env)
    assert len(refusals) == 1 and f"COGES_ENV vaut « {env} »" in refusals[0]
    assert _refusals(COGES_ENV="production") == []


def test_a_database_address_written_by_hand_is_refused() -> None:
    """Le compose compose les DSN : en écrire un, même juste, c'est risquer la mauvaise base."""
    good = "postgresql+psycopg://coges_app:x@postgres:5432/coges"
    refusals = _refusals(COGES_DATABASE_URL_APP=good)
    assert len(refusals) == 1 and "n'a rien à faire ici" in refusals[0]


def test_a_dsn_that_does_not_name_its_role_is_refused() -> None:
    refusals = _refusals(
        COGES_DATABASE_URL_APP="postgresql+psycopg://coges_analytics:x@postgres:5432/coges"
    )
    assert (
        "coges.env : COGES_DATABASE_URL_APP doit se connecter sous coges_app (lu : coges_analytics)"
        in refusals
    )


def test_a_dsn_towards_another_host_than_postgres_is_refused() -> None:
    refusals = _refusals(
        COGES_DATABASE_URL_APP="postgresql+psycopg://coges_app:x@192.168.1.20:5432/coges"
    )
    assert any("vise l'hôte « 192.168.1.20 »" in refusal for refusal in refusals)


@pytest.mark.parametrize(
    ("key", "value", "marker"),
    [
        (
            "COGES_DATABASE_URL_APP",
            "postgresql+psycopg://coges_app:x@ep-cool-1.eu-central-1.aws.neon.tech/coges?sslmode=require",
            "neon.tech",
        ),
        ("COGES_PUBLIC_URL", "https://coges.app", "coges.app"),
        ("COGES_MERCHANT_URL", "https://COGES.APP", "coges.app"),
        (
            "COGES_REDIS_URL",
            "rediss://default:x@redis-123.c1.eu-west-1.redns.redis-cloud.com:12345",
            "redis-cloud.com",
        ),
        ("COGES_ANYTHING", "ep%2Dcool.neon%2Etech", "neon.tech"),
    ],
)
def test_nothing_may_point_at_the_production_services(key: str, value: str, marker: str) -> None:
    """Garde-fou « jamais la production » : même par copier-coller, une installation sur
    site ne se branche pas sur la base ou les services des utilisateurs actuels."""
    refusals = _refusals(**{key: value})
    assert any(f"{key} contient « {marker} »" in refusal for refusal in refusals), refusals


def test_a_redis_url_outside_the_internal_network_is_refused() -> None:
    refusals = _refusals(COGES_REDIS_URL="redis://:x@10.0.0.5:6379/0")
    assert any("COGES_REDIS_URL vise « 10.0.0.5 »" in refusal for refusal in refusals)
    assert _refusals(COGES_REDIS_URL="redis://:x@redis:6379/0") != []  # composée par le compose


@pytest.mark.parametrize(
    "present",
    [
        {"COGES_VAPID_PUBLIC_KEY": "BPublic"},
        {"COGES_VAPID_PUBLIC_KEY": "BPublic", "COGES_VAPID_SUBJECT": "mailto:a@b.sn"},
        {"COGES_CLOUDINARY_CLOUD_NAME": "boutique"},
        {"COGES_CLOUDINARY_API_KEY": "123456", "COGES_CLOUDINARY_API_SECRET": "s" * 20},
    ],
)
def test_optional_settings_half_set_are_refused(present: dict[str, str]) -> None:
    refusals = _refusals(**present)
    assert len(refusals) == 1 and "à moitié posés" in refusals[0]


@pytest.mark.parametrize(
    "present",
    [
        {
            "COGES_VAPID_PUBLIC_KEY": "BPublic",
            "COGES_VAPID_PRIVATE_KEY": "prive",
            "COGES_VAPID_SUBJECT": "mailto:a@b.sn",
        },
        {"COGES_SMTP_HOST": "smtp.exemple.sn"},
        {"COGES_SENTRY_DSN": "https://k@o1.ingest.sentry.io/1"},
        {"COGES_JOB_PING_URLS": '{"x": "https://hc-ping.com/1"}'},
        {"COGES_SIGNUP_ENABLED": "true"},
    ],
)
def test_optional_services_stay_off_on_site(present: dict[str, str]) -> None:
    refusals = _refusals(**present)
    assert len(refusals) == 1, refusals


@pytest.mark.parametrize(
    ("port", "url", "accepted"),
    [
        ("80", "http://localhost", True),
        ("8080", "http://localhost:8080", True),
        ("8080", "http://localhost", False),
        ("80", "http://localhost:8080", False),
        ("80", "https://localhost", False),
        ("80", "http://192.168.1.10", False),
        ("quatre-vingts", "http://localhost", False),
    ],
)
def test_the_port_and_the_address_go_together(port: str, url: str, accepted: bool) -> None:
    refusals = _refusals(COGES_HTTP_PORT=port, COGES_PUBLIC_URL=url)
    assert (refusals == []) is accepted, refusals


def test_a_settings_file_saved_by_notepad_with_windows_line_endings_is_accepted() -> None:
    """`docker compose --env-file` lit un fichier en CRLF comme un fichier en LF : le
    contrôle n'ajoute pas un refus que le démarrage n'aurait pas."""
    text = _text().replace("\n", "\r\n")
    assert check.env_file_violations(text, source="coges.env") == []
    assert check.read_env_file(text) == _values()


def test_the_refusals_are_printed_in_french_with_a_failing_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / "coges.env"
    env_file.write_text(_text(COGES_IMAGE_TAG="latest"), encoding="utf-8")
    assert check.main(["--env-file", str(env_file)]) == 1
    captured = capsys.readouterr().err
    assert captured.startswith("REFUS — coges.env : COGES_IMAGE_TAG vaut « latest »")
    assert "1 point(s) à corriger" in captured


def test_a_file_written_by_powershell_in_utf16_is_read(tmp_path: Path) -> None:
    rendered = tmp_path / "rendu.json"
    rendered.write_text(json.dumps({"services": {}}), encoding="utf-16")
    env_file = tmp_path / "coges.env"
    env_file.write_bytes(b"\xef\xbb\xbf" + _text().encode())
    assert check.main(["--env-file", str(env_file), "--rendered", str(rendered)]) == 0


def test_the_script_uses_the_standard_library_only() -> None:
    result = subprocess.run(
        ["python3", "-I", "-S", str(ONPREM / "check_onprem_env.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_the_role_whitelist_is_the_one_of_the_vps_check() -> None:
    """Le dossier est autonome : la liste blanche de l'ADR 0088 y est recopiée, et ce test
    la tient identique à celle de check_runtime_env.py."""
    reference = _load(REPO / "deploy" / "scripts" / "check_runtime_env.py")
    assert check.RUNTIME_DSNS == reference.RUNTIME_DSNS
    assert check.MIN_SECRET_LENGTH == reference.MIN_SECRET_LENGTH


# ------------------------------------------------------------------ le compose rendu


def _rendered(**services: dict[str, Any]) -> dict[str, Any]:
    base: dict[str, Any] = {
        "api": {
            "image": "ghcr.io/papa-bothie/coges/api:v1.4.0",
            "environment": {
                "COGES_ENV": "production",
                "COGES_DATABASE_URL_APP": "postgresql+psycopg://coges_app:x@postgres:5432/coges",
                "COGES_REDIS_URL": "redis://:x@redis:6379/0",
            },
        },
        "migrate": {
            "image": "ghcr.io/papa-bothie/coges/worker:v1.4.0",
            "environment": {
                "COGES_ENV": "production",
                "COGES_DATABASE_URL_OWNER": "postgresql+psycopg://coges_owner:x@postgres:5432/coges",
            },
        },
        "caddy": {
            "image": "caddy:2.10.2-alpine",
            "ports": [{"host_ip": "127.0.0.1", "published": "80", "target": 80}],
        },
    }
    for name, changes in services.items():
        merged = {**base.get(name, {}), **changes}
        if "environment" in changes and name in base:
            merged["environment"] = {**base[name].get("environment", {}), **changes["environment"]}
        base[name] = merged
    return {"services": base}


def _rendered_refusals(**services: dict[str, Any]) -> list[str]:
    found: list[str] = check.rendered_violations(_rendered(**services), source="rendu")
    return found


def test_the_expected_rendering_passes() -> None:
    assert _rendered_refusals() == []


@pytest.mark.parametrize("service", ["api", "worker", "beat", "relay", "cli"])
def test_the_owner_dsn_in_a_continuous_service_is_refused(service: str) -> None:
    owner = "postgresql+psycopg://coges_owner:x@postgres:5432/coges"
    refusals = _rendered_refusals(**{service: {"environment": {"COGES_DATABASE_URL_OWNER": owner}}})
    assert refusals == [
        f"rendu : service {service} : reçoit le DSN de coges_owner (COGES_DATABASE_URL_OWNER) : "
        "il est réservé au service ponctuel migrate"
    ]


def test_the_owner_hidden_under_a_runtime_variable_is_refused() -> None:
    owner = "postgresql+psycopg://coges_owner:x@postgres:5432/coges"
    refusals = _rendered_refusals(api={"environment": {"COGES_DATABASE_URL_APP": owner}})
    assert len(refusals) == 1 and "reçoit le DSN de coges_owner" in refusals[0]


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql+psycopg://coges_relay:x@postgres:5432/coges",
        "postgresql+psycopg://postgres:x@postgres:5432/coges",
        "postgresql+psycopg://coges%5Fbackup:x@postgres:5432/coges",
        "postgresql+psycopg://coges_app:x@postgres:5432/coges?user=coges_backup",
    ],
)
def test_a_rendered_dsn_must_name_its_own_role(dsn: str) -> None:
    refusals = _rendered_refusals(api={"environment": {"COGES_DATABASE_URL_APP": dsn}})
    assert len(refusals) == 1 and "doit se connecter sous coges_app" in refusals[0]


@pytest.mark.parametrize("host", ["localhost", "db.exemple.sn", "ep-x.eu-central-1.aws.neon.tech"])
def test_a_rendered_dsn_must_target_the_postgres_service(host: str) -> None:
    dsn = f"postgresql+psycopg://coges_app:x@{host}:5432/coges"
    refusals = _rendered_refusals(api={"environment": {"COGES_DATABASE_URL_APP": dsn}})
    assert any(f"vise l'hôte « {host} »" in refusal for refusal in refusals)


def test_a_rendered_redis_outside_the_internal_network_is_refused() -> None:
    refusals = _rendered_refusals(
        api={"environment": {"COGES_REDIS_URL": "redis://:x@10.0.0.5:6379/0"}}
    )
    assert len(refusals) == 1 and "hors du réseau interne" in refusals[0]


def test_a_rendered_environment_other_than_production_is_refused() -> None:
    refusals = _rendered_refusals(api={"environment": {"COGES_ENV": "local"}})
    assert refusals == ["rendu : service api : COGES_ENV vaut « local », pas production"]


@pytest.mark.parametrize(
    "image", ["ghcr.io/papa-bothie/coges/api:latest", "ghcr.io/papa-bothie/coges/api"]
)
def test_a_rendered_application_image_needs_a_precise_tag(image: str) -> None:
    refusals = _rendered_refusals(api={"image": image})
    assert len(refusals) == 1 and "l'étiquette de l'image" in refusals[0]


@pytest.mark.parametrize("host_ip", ["0.0.0.0", None, "192.168.1.10"])  # noqa: S104
def test_a_port_published_outside_the_loopback_is_refused(host_ip: str | None) -> None:
    port = {"published": "80", "target": 80} | ({"host_ip": host_ip} if host_ip else {})
    refusals = _rendered_refusals(caddy={"ports": [port]})
    assert len(refusals) == 1 and "hors de la boucle locale" in refusals[0]


# ------------------------------------------------------------------ chemins protégés


def test_a_change_to_the_vps_caddyfile_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert paths.main(["--paths", "deploy/vps/Caddyfile", "deploy/onprem/Caddyfile"]) == 1
    assert "REFUS — deploy/vps/Caddyfile est un chemin protégé" in capsys.readouterr().err


def test_an_addition_in_the_on_site_folder_passes(capsys: pytest.CaptureFixture[str]) -> None:
    added = [
        "deploy/onprem/docker-compose.yml",
        "deploy/onprem-ci/verifier.sh",
        ".github/workflows/onprem.yml",
        "backend/tests/unit/test_onprem_scripts.py",
        "docs/runbooks/sur-site.md",
        "docs/decisions/0124-assemblage-sur-site.md",
        "CLAUDE.md",
    ]
    assert paths.main(["--paths", *added]) == 0
    assert "OK" in capsys.readouterr().out


@pytest.mark.parametrize(
    "path",
    [
        "deploy/vps/docker-compose.yml",
        "deploy/scripts/check_runtime_env.py",
        "deploy/postgres/init/01-roles.sql",
        "deploy/sql/create_signup_role.sql",
        "docker-compose.yml",
        "backend/app/core/config.py",
        "backend/migrations/versions/0043_x.py",
        "backend/Dockerfile.api",
        "backend/Dockerfile.worker",
        "backend/pyproject.toml",
        "backend/uv.lock",
        "frontend/next.config.ts",
        "frontend-admin/package.json",
        ".github/workflows/deploy.yml",
        ".github/workflows/backup.yml",
        ".github/workflows/backup-retention.yml",
    ],
)
def test_every_protected_path_is_recognised(path: str) -> None:
    assert paths.is_protected(path), path


@pytest.mark.parametrize(
    "path",
    [
        "deploy/onprem/docker-compose.yml",
        "deploy/README-infra.md",
        "backend/tests/unit/test_onprem_configuration.py",
        "backend/README.md",
        ".github/workflows/onprem.yml",
        ".github/workflows/ci.yml",
        "docs/runbooks/sur-site.md",
        "frontend.md",
    ],
)
def test_the_rest_of_the_repository_stays_open(path: str) -> None:
    assert not paths.is_protected(path), path


def test_the_comparison_reads_git_against_the_base_branch(tmp_path: Path) -> None:
    """Sur un vrai dépôt : un fichier protégé modifié dans la branche est nommé."""

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-b", "main")
    (tmp_path / "deploy" / "vps").mkdir(parents=True)
    (tmp_path / "deploy" / "vps" / "Caddyfile").write_text("avant\n")
    git("add", ".")
    git("commit", "-m", "base")
    git("checkout", "-b", "feat/sur-site-x")
    (tmp_path / "deploy" / "onprem").mkdir()
    (tmp_path / "deploy" / "onprem" / "Caddyfile").write_text("neuf\n")
    git("add", ".")
    git("commit", "-m", "ajout")
    script = str(ONPREM / "check_protected_paths.py")
    run = ["python3", script, "--base", "main"]
    assert subprocess.run(run, cwd=tmp_path, capture_output=True, check=False).returncode == 0

    (tmp_path / "deploy" / "vps" / "Caddyfile").write_text("après\n")
    git("commit", "-am", "modification interdite")
    refused = subprocess.run(run, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert refused.returncode == 1
    assert "deploy/vps/Caddyfile est un chemin protégé" in refused.stderr
