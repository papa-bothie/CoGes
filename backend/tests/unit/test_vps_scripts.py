"""Scripts du VPS (ADR 0083) : arguments de deploy.sh, essai à blanc de bootstrap.sh.

deploy.sh est lancé par une clé SSH bridée : ses arguments arrivent dans
SSH_ORIGINAL_COMMAND, écrits par n'importe qui détient la clé. Rien de ce texte ne doit
être interprété par le shell, et seuls une pile connue et une version bien formée passent.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

VPS = Path(__file__).resolve().parents[3] / "deploy" / "vps"
DEPLOY = VPS / "deploy.sh"


def _deploy(
    tmp_path: Path, *args: str, ssh_command: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"],
        "COGES_ROOT": str(tmp_path / "opt"),
        "COGES_ETC": str(tmp_path / "etc"),
        "COGES_LOG_DIR": str(tmp_path / "log"),
    }
    if ssh_command is not None:
        env["SSH_ORIGINAL_COMMAND"] = ssh_command
    return subprocess.run(
        ["bash", str(DEPLOY), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_without_arguments_deploy_prints_its_usage(tmp_path: Path) -> None:
    result = _deploy(tmp_path)
    assert result.returncode == 2
    assert "deploy.sh <production|preprod>" in result.stdout


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("staging", "v1.2.3"), "pile inconnue"),
        (("production", "1.2.3"), "version refusée"),
        (("production", "v1.2"), "version refusée"),
        (("production", "latest"), "version refusée"),
        (("production", "v1.2.3;id"), "version refusée"),
        (("production", "stop"), "seule la préproduction"),
    ],
)
def test_deploy_refuses_unknown_stacks_and_versions(
    tmp_path: Path, args: tuple[str, str], message: str
) -> None:
    result = _deploy(tmp_path, *args)
    assert result.returncode == 1
    assert message in result.stdout


def test_a_valid_request_goes_on_to_the_secrets_file(tmp_path: Path) -> None:
    result = _deploy(tmp_path, "production", "v1.2.3")
    assert result.returncode == 1
    assert "fichier de secrets illisible" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "production v1.2.3; touch PWNED",
        "production $(touch PWNED)",
        "production `touch PWNED`",
        "production v1.2.3 && touch PWNED",
        "preprod v1.0.0 extra",
    ],
)
def test_the_restricted_key_cannot_inject_commands(tmp_path: Path, command: str) -> None:
    result = _deploy(tmp_path, ssh_command=command)
    assert result.returncode in {1, 2}
    assert not (tmp_path / "PWNED").exists()
    assert not Path("PWNED").exists()


def test_the_restricted_key_may_name_the_script(tmp_path: Path) -> None:
    result = _deploy(tmp_path, ssh_command="/opt/coges/deploy.sh production v1.2.3")
    assert "fichier de secrets illisible" in result.stdout


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker absent")
def test_bootstrap_dry_run_on_ubuntu_24_04_changes_nothing() -> None:
    """Essai à blanc dans un conteneur Ubuntu 24.04 : chaque étape se déroule, rien n'est
    appliqué, et le script dit ce qu'il ferait (pas une machine virtuelle complète)."""
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{VPS}:/vps:ro",
                "ubuntu:24.04",
                "bash",
                "/vps/bootstrap.sh",
                "--dry-run",
                "--ssh-port",
                "2222",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("image ubuntu:24.04 indisponible à temps")
    if "Unable to find image" in result.stderr and result.returncode != 0:
        pytest.skip("image ubuntu:24.04 indisponible")
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "rien n'a été changé" in out
    assert "[essai] ufw allow 2222/tcp comment ssh" in out
    assert "[essai] écrirait /etc/ssh/sshd_config.d/10-coges.conf" in out
    assert "[essai] écrirait /etc/apt/apt.conf.d/52coges-unattended" in out
    # Le conteneur voit le swap de l'hôte : déjà actif sur certains runners.
    assert "[essai] fallocate -l 2G /swapfile" in out or "swap : déjà actif" in out
    assert "[essai] install -m 0755 -o root -g root /vps/deploy.sh /opt/coges/deploy.sh" in out


def test_bootstrap_refuses_an_invalid_ssh_port() -> None:
    result = subprocess.run(
        ["bash", str(VPS / "bootstrap.sh"), "--dry-run", "--ssh-port", "99999"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert "port SSH invalide" in result.stderr


def test_the_maintenance_page_stands_alone() -> None:
    """Servie par Caddy quand le front ou l'API est arrêté (ADR 0085) : rien d'extérieur."""
    page = (VPS / "maintenance.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    assert '<html lang="fr">' in page
    assert "Vos données sont en sécurité" in page
    for outside in ("<script", "<link", "src=", "url(", "http://", "https://", "@import"):
        assert outside not in page, outside
    assert "prefers-color-scheme: dark" in page


def test_caddy_serves_the_maintenance_page_on_gateway_errors() -> None:
    caddyfile = (VPS / "Caddyfile").read_text(encoding="utf-8")
    compose = (VPS / "docker-compose.yml").read_text(encoding="utf-8")
    bundle = (VPS / "Dockerfile.bundle").read_text(encoding="utf-8")
    assert "handle_errors 502 503 504" in caddyfile
    assert "rewrite * /maintenance.html" in caddyfile
    assert "./maintenance.html:/srv/maintenance/maintenance.html:ro" in compose
    assert "deploy/vps/maintenance.html" in bundle


# ------------------------------------------------- deploy.sh de bout en bout (P2.19, ADR 0088)
#
# Faux `docker` et faux `curl` : `up -d` note la version lancée (ou échoue sur demande),
# `curl` répond selon la version qui tourne. Aucune vraie pile n'est démarrée.

_DOCKER = """#!/usr/bin/env bash
echo "docker $* COGES_STACK=${COGES_STACK:-} TAG=${COGES_IMAGE_TAG:-}" >>"$FAKE_LOG"
case "$1" in
  compose)
    if [[ " $* " == *" up "* ]]; then
      [[ "${COGES_IMAGE_TAG}" == "${FAKE_FAIL_UP:-}" ]] && exit 1
      echo "${COGES_IMAGE_TAG}" >"$FAKE_RUNNING"
    fi ;;
  image)
    if [[ "$2" == ls ]]; then printf '%s\\n' $FAKE_IMAGES; fi ;;
esac
exit 0
"""

_CURL = """#!/usr/bin/env bash
running=$(cat "$FAKE_RUNNING" 2>/dev/null || true)
[[ " ${FAKE_BROKEN:-} " == *" $running "* ]] && exit 22
for arg in "$@"; do url=$arg; done
if [[ "$url" == */health/ready ]]; then echo '{"status":"ok"}'; exit 0; fi
# Une vraie page : « Connexion » tôt, puis beaucoup de HTML. `grep -q` s'arrête au
# premier mot trouvé, et curl reçoit SIGPIPE en écrivant la suite.
echo "<title>Connexion</title>"
head -c 3000000 /dev/zero | tr '\\0' 'x'
"""

_VPS_ENV = """COGES_STACK={stack}
COGES_DOMAIN=app.exemple.sn
COGES_DATABASE_URL_APP=postgresql+psycopg://coges_app:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require
COGES_DATABASE_URL_RELAY=postgresql+psycopg://coges_relay:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require
COGES_DATABASE_URL_ANALYTICS=postgresql+psycopg://coges_analytics:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require
COGES_DATABASE_URL_PLATFORM=postgresql+psycopg://coges_app_platform:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require
COGES_ADMIN_ALLOWED_IPS=192.0.2.10
COGES_REDIS_PASSWORD=ci-redis-password-00000000000000000000
COGES_JWT_SECRET=ci-jwt-secret-0000000000000000000000
COGES_MFA_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
"""


def _stage(
    tmp_path: Path, *, stack: str, env_stack: str, versions: tuple[str, ...]
) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", _DOCKER), ("curl", _CURL)):
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    etc = tmp_path / "etc"
    etc.mkdir()
    env_name = "coges.env" if stack == "production" else "preprod.env"
    (etc / env_name).write_text(_VPS_ENV.format(stack=env_stack), encoding="utf-8")
    for version in versions:
        release = tmp_path / "opt" / "releases" / version
        release.mkdir(parents=True)
        (release / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        shutil.copy(VPS.parent / "scripts" / "check_runtime_env.py", release)
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "COGES_ROOT": str(tmp_path / "opt"),
        "COGES_ETC": str(etc),
        "COGES_LOG_DIR": str(tmp_path / "log"),
        "COGES_DEPLOY_WAIT": "1",
        "FAKE_LOG": str(tmp_path / "docker.log"),
        "FAKE_RUNNING": str(tmp_path / "running"),
    }


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(DEPLOY), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _state(tmp_path: Path, stack: str, version: str, previous: str | None = None) -> None:
    state = tmp_path / "opt" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / f"{stack}.version").write_text(f"{version}\n", encoding="utf-8")
    if previous:
        (state / f"{stack}.previous").write_text(f"{previous}\n", encoding="utf-8")


def test_a_healthy_deploy_is_not_failed_by_a_long_login_page(tmp_path: Path) -> None:
    env = _stage(tmp_path, stack="production", env_stack="production", versions=("v1.0.0",))
    result = _run(env, "production", "v1.0.0")
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_failing_up_rolls_back_to_the_previous_version(tmp_path: Path) -> None:
    env = _stage(
        tmp_path, stack="production", env_stack="production", versions=("v1.0.0", "v1.1.0")
    )
    _state(tmp_path, "production", "v1.0.0")
    env["FAKE_FAIL_UP"] = "v1.1.0"

    result = _run(env, "production", "v1.1.0")

    assert result.returncode == 1
    log = (tmp_path / "docker.log").read_text(encoding="utf-8")
    assert "up -d" in log and "TAG=v1.0.0" in log.split("TAG=v1.1.0")[-1], (
        "aucun retour à v1.0.0 après l'échec de up -d"
    )
    assert (tmp_path / "running").read_text().strip() == "v1.0.0"


def test_a_preprod_env_file_copied_from_production_is_refused(tmp_path: Path) -> None:
    env = _stage(tmp_path, stack="preprod", env_stack="production", versions=("v1.0.0",))
    result = _run(env, "preprod", "v1.0.0")
    assert result.returncode == 1
    assert "COGES_STACK" in result.stdout + result.stderr
    assert not (tmp_path / "running").exists(), "la préproduction a démarré sous les alias de prod"


def test_compose_always_receives_the_stack_being_started(tmp_path: Path) -> None:
    env = _stage(tmp_path, stack="preprod", env_stack="preprod", versions=("v1.0.0",))
    result = _run(env, "preprod", "v1.0.0")
    assert result.returncode == 0, result.stdout + result.stderr
    ups = [line for line in (tmp_path / "docker.log").read_text().splitlines() if " up " in line]
    assert ups and all("COGES_STACK=preprod" in line for line in ups)


def test_old_images_are_removed_but_current_and_previous_kept(tmp_path: Path) -> None:
    env = _stage(tmp_path, stack="production", env_stack="production", versions=("v1.2.0",))
    _state(tmp_path, "production", "v1.1.0", previous="v1.0.0")
    registry = "ghcr.io/papa-bothie/coges"
    env["FAKE_IMAGES"] = " ".join(
        f"{registry}/{package}:{version}"
        for package in ("api", "front")
        for version in ("v0.9.0", "v1.0.0", "v1.1.0", "v1.2.0")
    )

    result = _run(env, "production", "v1.2.0")

    assert result.returncode == 0, result.stdout + result.stderr
    removed = [
        line for line in (tmp_path / "docker.log").read_text().splitlines() if "image rm" in line
    ]
    assert any(":v0.9.0" in line for line in removed) and any(":v1.0.0" in line for line in removed)
    assert not any(":v1.1.0" in line or ":v1.2.0" in line for line in removed), removed


# ------------------------------------------- porte de l'administration (ADR 0104)

_ACCESS = (
    "COGES_ADMIN_GATE=cloudflare\n"
    "COGES_ACCESS_TEAM_DOMAIN=coges.cloudflareaccess.com\n"
    f"COGES_ACCESS_AUD={'a' * 64}\n"
    f"COGES_CLOUDFLARE_TUNNEL_TOKEN={'t' * 120}\n"
)


def _compose_lines(tmp_path: Path) -> list[str]:
    log = (tmp_path / "docker.log").read_text(encoding="utf-8")
    return [line for line in log.splitlines() if line.startswith("docker compose")]


def test_the_cloudflare_gate_starts_the_tunnel(tmp_path: Path) -> None:
    env = _stage(tmp_path, stack="production", env_stack="production", versions=("v1.0.0",))
    with (tmp_path / "etc" / "coges.env").open("a", encoding="utf-8") as file:
        file.write(_ACCESS)
    result = _run(env, "production", "v1.0.0")
    assert result.returncode == 0, result.stdout + result.stderr
    ups = [line for line in _compose_lines(tmp_path) if " up " in line]
    assert ups and all("--profile edge --profile tunnel" in line for line in ups)
    assert not any(" rm " in line for line in _compose_lines(tmp_path))


def test_the_ip_gate_stops_a_tunnel_left_running(tmp_path: Path) -> None:
    """Retour arrière : cloudflared, hors profil, ne serait pas arrêté par `up`."""
    env = _stage(tmp_path, stack="production", env_stack="production", versions=("v1.0.0",))
    result = _run(env, "production", "v1.0.0")
    assert result.returncode == 0, result.stdout + result.stderr
    lines = _compose_lines(tmp_path)
    assert not any("--profile tunnel up" in line for line in lines)
    assert any("--profile tunnel rm --stop --force cloudflared" in line for line in lines)


def test_the_preprod_never_touches_the_tunnel(tmp_path: Path) -> None:
    env = _stage(tmp_path, stack="preprod", env_stack="preprod", versions=("v1.0.0",))
    with (tmp_path / "etc" / "preprod.env").open("a", encoding="utf-8") as file:
        file.write(_ACCESS)
    result = _run(env, "preprod", "v1.0.0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any("tunnel" in line for line in _compose_lines(tmp_path))


# ------------------------- retour impossible : la précédente refuse le fichier (3cafc49)

_REFUSING_CHECK = """import sys
print("REFUS — coges.env : COGES_ADMIN_ALLOWED_IPS est vide", file=sys.stderr)
sys.exit(1)
"""


def _refusing(tmp_path: Path, version: str) -> None:
    """Une version d'avant le changement du fichier de secrets : son contrôle le refuse."""
    release = tmp_path / "opt" / "releases" / version / "check_runtime_env.py"
    release.write_text(_REFUSING_CHECK, encoding="utf-8")


def test_when_the_previous_version_refuses_the_env_file_deploy_says_what_to_do(
    tmp_path: Path,
) -> None:
    env = _stage(
        tmp_path, stack="production", env_stack="production", versions=("v1.0.0", "v1.1.0")
    )
    (tmp_path / "log").mkdir()
    _state(tmp_path, "production", "v1.0.0", previous="v0.9.0")
    _refusing(tmp_path, "v1.0.0")
    env["FAKE_BROKEN"] = "v1.1.0"

    result = _run(env, "production", "v1.1.0")

    out = result.stdout + result.stderr
    assert result.returncode == 1
    # Prévenu avant de commencer, puis la raison, l'état réel et les deux issues.
    assert "pas de retour automatique possible" in out
    assert "COGES_ADMIN_ALLOWED_IPS est vide" in out
    assert "RETOUR IMPOSSIBLE" in out
    assert "tourne sur v1.1.0" in out
    assert "deploy.sh production v1.1.0" in out
    assert "deploy.sh production v1.0.0" in out
    assert "pas « rollback »" in out
    # Le même texte dans le journal, et aucun `up` de v1.0.0 tenté pour rien.
    journal = (tmp_path / "log" / "deploy.log").read_text(encoding="utf-8")
    assert "RETOUR IMPOSSIBLE" in journal and "deploy.sh production v1.0.0" in journal
    ups = [line for line in _compose_lines(tmp_path) if " up " in line]
    assert ups and all("TAG=v1.1.0" in line for line in ups)
    # L'état ne bouge pas : la version courante connue reste v1.0.0.
    state = tmp_path / "opt" / "state"
    assert (state / "production.version").read_text().strip() == "v1.0.0"


def test_an_env_file_refused_by_the_new_version_changes_nothing(tmp_path: Path) -> None:
    env = _stage(
        tmp_path, stack="production", env_stack="production", versions=("v1.0.0", "v1.1.0")
    )
    _state(tmp_path, "production", "v1.0.0")
    _refusing(tmp_path, "v1.1.0")

    result = _run(env, "production", "v1.1.0")

    out = result.stdout + result.stderr
    assert result.returncode == 1
    assert "COGES_ADMIN_ALLOWED_IPS est vide" in out
    assert "rien n'a été changé" in out
    assert not any(" up " in line for line in _compose_lines(tmp_path))


# ------------------------------------------- scripts du VPS dans le bundle (ADR 0105)


def _bundle_scripts(tmp_path: Path, version: str, scripts_version: int) -> None:
    scripts = tmp_path / "opt" / "releases" / version / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    body = DEPLOY.read_text(encoding="utf-8").replace(
        "\nSCRIPTS_VERSION=", f"\nSCRIPTS_VERSION={scripts_version}\n# était : ", 1
    )
    (scripts / "deploy.sh").write_text(body, encoding="utf-8")
    shutil.copy(VPS / "check.sh", scripts / "check.sh")


def _installed_scripts_version() -> int:
    match = re.search(r"^SCRIPTS_VERSION=(\d+)$", DEPLOY.read_text(encoding="utf-8"), re.M)
    assert match, "SCRIPTS_VERSION absent de deploy.sh"
    return int(match.group(1))


def test_the_bundle_carries_the_vps_scripts() -> None:
    bundle = (VPS / "Dockerfile.bundle").read_text(encoding="utf-8")
    assert "COPY deploy/vps/deploy.sh deploy/vps/check.sh /bundle/scripts/" in bundle
    assert _installed_scripts_version() >= 2


def test_newer_scripts_in_the_bundle_stop_the_deploy_before_any_change(tmp_path: Path) -> None:
    env = _stage(
        tmp_path, stack="production", env_stack="production", versions=("v1.0.0", "v1.1.0")
    )
    _state(tmp_path, "production", "v1.0.0")
    _bundle_scripts(tmp_path, "v1.1.0", _installed_scripts_version() + 1)

    result = _run(env, "production", "v1.1.0")

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "rien n'a été changé" in output
    release = tmp_path / "opt" / "releases" / "v1.1.0" / "scripts"
    assert f"sudo install -m 0755 -o root -g root {release}/deploy.sh" in output
    assert f"{release}/check.sh" in output
    assert not (tmp_path / "running").exists(), "la pile a été touchée"
    assert not any(" up " in line for line in _compose_lines(tmp_path) if "docker compose" in line)


@pytest.mark.parametrize("offset", [0, -1])
def test_same_or_older_scripts_deploy_normally(tmp_path: Path, offset: int) -> None:
    """Un retour arrière vers une version aux scripts plus anciens reste possible."""
    env = _stage(tmp_path, stack="production", env_stack="production", versions=("v1.0.0",))
    _bundle_scripts(tmp_path, "v1.0.0", _installed_scripts_version() + offset)
    result = _run(env, "production", "v1.0.0")
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_bundle_without_scripts_still_deploys(tmp_path: Path) -> None:
    """Bundles d'avant l'ADR 0105 : rien à comparer."""
    env = _stage(tmp_path, stack="production", env_stack="production", versions=("v1.0.0",))
    assert _run(env, "production", "v1.0.0").returncode == 0
