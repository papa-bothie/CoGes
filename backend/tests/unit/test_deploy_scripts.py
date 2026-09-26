"""Garde-fou 2 de l'ADR 0042 : le contrôle des environnements d'exécution."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "scripts" / "check_runtime_env.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_runtime_env", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_versioned_worker_compose_holds_no_owner_dsn() -> None:
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


def test_missing_vercel_token_fails_when_required(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    assert _module().main(["--require-vercel"]) == 1
