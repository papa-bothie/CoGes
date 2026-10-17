"""Garde-fou 2 de l'ADR 0042 : le contrôle des environnements d'exécution."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "scripts" / "check_runtime_env.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_runtime_env", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_versioned_compose_files_hold_no_owner_dsn() -> None:
    assert _module().main([]) == 0


def test_owner_variable_or_dsn_is_refused() -> None:
    check = _module()
    assert check.violations(
        [
            ("COGES_DATABASE_URL_APP", "postgresql+psycopg://coges_app:x@h/db"),
            ("COGES_DATABASE_URL_OWNER", "postgresql+psycopg://coges_owner:x@h/db"),
            ("DATABASE_URL", "postgres://coges_owner@h/db"),
        ],
        source="test",
    ) == [
        "test : la variable COGES_DATABASE_URL_OWNER ne doit pas exister à l'exécution",
        "test : DATABASE_URL désigne l'utilisateur coges_owner",
    ]


def test_compose_mentioning_the_owner_is_refused(tmp_path: Path) -> None:
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "services:\n  worker:\n    environment:\n"
        "      COGES_DATABASE_URL_OWNER: ${COGES_DATABASE_URL_OWNER}\n",
        encoding="utf-8",
    )
    assert _module().main(["--compose", str(compose)]) == 1


def test_vps_requires_an_env_file() -> None:
    assert _module().main(["--require-vps"]) == 1


_GOOD_ENV = """
# Pile de production (ADR 0083)
COGES_STACK=production
COGES_DOMAIN=app.exemple.sn
COGES_DATABASE_URL_APP=postgresql+psycopg://coges_app:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require
COGES_DATABASE_URL_RELAY=postgresql+psycopg://coges_relay:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require
COGES_DATABASE_URL_ANALYTICS="postgresql+psycopg://coges_analytics:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require"
COGES_REDIS_PASSWORD=ci-redis-password-00000000000000000000
COGES_JWT_SECRET=ci-jwt-secret-0000000000000000000000
"""


def _env(tmp_path: Path, text: str) -> list[str]:
    path = tmp_path / "coges.env"
    path.write_text(text, encoding="utf-8")
    return ["--require-vps", "--env-file", str(path)]


def test_a_complete_vps_env_file_passes(tmp_path: Path) -> None:
    assert _module().main(_env(tmp_path, _GOOD_ENV)) == 0


def test_the_example_env_file_is_refused_until_filled() -> None:
    example = SCRIPT.parents[1] / "vps" / "coges.env.example"
    assert _module().main(["--require-vps", "--env-file", str(example)]) == 1


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (("sslmode=require", "sslmode=disable"), "sslmode=require"),
        (("ep-1.eu-central-1.aws.neon.tech", "localhost"), "base locale"),
        (("COGES_DOMAIN=app.exemple.sn", "COGES_DOMAIN=https://app.exemple.sn"), "nom d'hôte nu"),
        (("COGES_DOMAIN=app.exemple.sn", "COGES_DOMAIN="), "COGES_DOMAIN invalide"),
        (("COGES_JWT_SECRET=ci-jwt-secret-0000000000000000000000", "COGES_JWT_SECRET=court"), "32"),
        (
            ("COGES_STACK=production", "COGES_REDIS_URL=redis://:p@redis.example.com:6379/0"),
            "Redis interne",
        ),
        (
            ("COGES_STACK=production", "COGES_DATABASE_URL_OWNER=postgresql://coges_owner:x@h/db"),
            "COGES_DATABASE_URL_OWNER",
        ),
        (
            ("coges_app:x", "coges_owner:x"),
            "coges_owner",
        ),
    ],
)
def test_vps_env_file_rules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: tuple[str, str], reason: str
) -> None:
    text = _GOOD_ENV.replace(*change)
    assert _module().main(_env(tmp_path, text)) == 1
    assert reason in capsys.readouterr().err
