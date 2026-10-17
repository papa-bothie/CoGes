"""Scripts du VPS (ADR 0083) : arguments de deploy.sh, essai à blanc de bootstrap.sh.

deploy.sh est lancé par une clé SSH bridée : ses arguments arrivent dans
SSH_ORIGINAL_COMMAND, écrits par n'importe qui détient la clé. Rien de ce texte ne doit
être interprété par le shell, et seuls une pile connue et une version bien formée passent.
"""

from __future__ import annotations

import os
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
