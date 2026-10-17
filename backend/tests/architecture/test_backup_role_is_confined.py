"""Le rôle de sauvegarde ne sert qu'au workflow de sauvegarde (ADR 0084).

`coges_backup` se connecte et franchit la RLS : c'est l'exception nommée de T36. Il ne
doit donc jamais pouvoir servir à l'exécution : l'API et les workers refusent de
démarrer sous lui (garde-fou 1), aucun code applicatif ne le nomme, et son DSN n'existe
ni dans les fichiers du VPS ni dans un fichier de secrets accepté par deploy.sh.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.core.role_guard import ForbiddenRuntimeRoleError, check_role

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "backend" / "app"


def test_runtime_refuses_the_backup_role() -> None:
    with pytest.raises(ForbiddenRuntimeRoleError):
        check_role("coges_backup", True)


def test_no_application_code_names_the_backup_role() -> None:
    offenders = [
        str(path.relative_to(REPO))
        for path in APP.rglob("*.py")
        if "coges_backup" in (text := path.read_text(encoding="utf-8"))
        or "BACKUP_DATABASE_URL" in text
    ]
    assert offenders == []


def test_the_vps_files_never_carry_the_backup_dsn() -> None:
    for path in (REPO / "deploy" / "vps").iterdir():
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "coges_backup" not in text, path.name
            assert "BACKUP_DATABASE_URL" not in text, path.name


def _check_runtime_env() -> ModuleType:
    script = REPO / "deploy" / "scripts" / "check_runtime_env.py"
    spec = importlib.util.spec_from_file_location("check_runtime_env", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_secrets_file_with_the_backup_dsn_is_refused() -> None:
    found = _check_runtime_env().violations(
        [("COGES_DATABASE_URL_APP", "postgresql+psycopg://coges_backup:x@h/db?sslmode=require")],
        source="test",
    )
    assert found == ["test : COGES_DATABASE_URL_APP désigne l'utilisateur coges_backup"]
