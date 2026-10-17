"""Scripts de la sauvegarde externe (ADR 0084) : rétention, refus de la restauration.

La chaîne complète (dump → chiffrement → restauration → vérification) est prouvée par
`deploy/scripts/backup_chain_check.sh`, joué en CI contre un vrai PostgreSQL. Ici, les
refus : ils doivent tenir avant même de toucher une base.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "deploy" / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------- rétention


def _names(*stamps: str) -> list[str]:
    names = []
    for stamp in stamps:
        names += [f"coges-{stamp}.dump.age", f"coges-{stamp}.dump.age.sha256"]
    return names


def test_the_last_seven_days_are_always_kept() -> None:
    retention = _load("backup_retention")
    names = _names(*(f"2026-10-{day:02d}-0215" for day in range(11, 18)), "2026-10-17-1100")
    assert retention.to_delete(names, date(2026, 10, 17)) == []


def test_sundays_are_kept_four_weeks_and_firsts_twelve_months() -> None:
    retention = _load("backup_retention")
    names = _names(
        "2026-10-04-0215",  # dimanche, 13 jours : gardée
        "2026-10-05-0215",  # lundi, 12 jours : supprimée
        "2026-09-13-0215",  # dimanche, 34 jours : supprimée
        "2026-10-01-0215",  # 1er octobre : gardée
        "2025-11-01-0215",  # 1er, moins d'un an : gardée
        "2025-10-01-0215",  # 1er, plus d'un an : supprimée
    )
    assert retention.to_delete(names, date(2026, 10, 17)) == _names(
        "2025-10-01-0215", "2026-09-13-0215", "2026-10-05-0215"
    )


def test_only_the_last_backup_of_a_kept_day_survives() -> None:
    retention = _load("backup_retention")
    names = _names("2026-10-04-0215", "2026-10-04-1830")
    assert retention.to_delete(names, date(2026, 10, 17)) == _names("2026-10-04-0215")


def test_unknown_files_are_never_touched() -> None:
    retention = _load("backup_retention")
    names = ["notes.txt", "coges-2020-01-02-0215.sql", "coges-2020-01-02.dump.age"]
    assert retention.to_delete(names, date(2026, 10, 17)) == []


def test_verify_restore_knows_the_head_revision() -> None:
    revisions = sorted(
        path.name[:4]
        for path in (SCRIPTS.parents[1] / "backend" / "migrations" / "versions").glob("0*.py")
    )
    assert _load("verify_restore").head_revision() == revisions[-1]


# --------------------------------------------------------------------- restauration


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    path = tmp_path / "coges-2026-10-17-0215.dump.age"
    path.write_bytes(b"contenu chiffre de test")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / f"{path.name}.sha256").write_text(f"{digest}  {path.name}\n")
    (tmp_path / "test.key").write_text("AGE-SECRET-KEY-TEST\n")
    return path


def _restore(
    archive: Path, target: str, *, production_host: str | None, psql_says: str = "0"
) -> subprocess.CompletedProcess[str]:
    # Un faux `psql` répond au comptage des tables de la cible : aucune base requise.
    bin_dir = archive.parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "psql"
    fake.write_text(f"#!/bin/sh\necho {psql_says}\n")
    fake.chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    if production_host is not None:
        env["COGES_PRODUCTION_DB_HOST"] = production_host
    return subprocess.run(
        [
            "bash",
            str(SCRIPTS / "restore_backup.sh"),
            str(archive),
            str(archive.parent / "test.key"),
            target,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_restore_refuses_a_modified_archive(archive: Path) -> None:
    archive.write_bytes(b"contenu altere")
    result = _restore(archive, "postgresql://u@secours.local/db", production_host="prod.neon.tech")
    assert result.returncode == 1
    assert "sha256 différent" in result.stderr


def test_restore_refuses_without_checksum(archive: Path) -> None:
    Path(f"{archive}.sha256").unlink()
    result = _restore(archive, "postgresql://u@secours.local/db", production_host="prod.neon.tech")
    assert result.returncode == 1
    assert "empreinte absente" in result.stderr


def test_restore_refuses_the_production_host(archive: Path) -> None:
    result = _restore(
        archive, "postgresql://u@EP-Prod.neon.tech/coges", production_host="ep-prod.neon.tech"
    )
    assert result.returncode == 1
    assert "base de production" in result.stderr


def test_restore_refuses_when_the_production_host_is_unknown(archive: Path) -> None:
    result = _restore(archive, "postgresql://u@secours.local/db", production_host=None)
    assert result.returncode != 0
    assert "COGES_PRODUCTION_DB_HOST" in result.stderr


def test_restore_refuses_a_database_that_is_not_empty(archive: Path) -> None:
    result = _restore(
        archive, "postgresql://u@secours.local/db", production_host="prod.neon.tech", psql_says="12"
    )
    assert result.returncode == 1
    assert "pas vide" in result.stderr


# --------------------------------------------------------------------- sauvegarde


@pytest.mark.parametrize(
    ("dsn", "allow_local", "recipient", "message"),
    [
        ("postgresql://coges_backup:x@ep.neon.tech/coges", "0", "age1abc", "sslmode=require"),
        ("postgresql://coges_backup:x@ep.neon.tech/coges", "1", "age1abc", "sslmode=require"),
        (
            "postgresql://coges_backup:x@ep.neon.tech/coges?sslmode=require",
            "0",
            "ssh-ed25519",
            "clé publique age",
        ),
    ],
)
def test_backup_refuses_unsafe_settings(
    tmp_path: Path, dsn: str, allow_local: str, recipient: str, message: str
) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPTS / "backup.sh")],
        env={
            "PATH": os.environ["PATH"],
            "BACKUP_DATABASE_URL": dsn,
            "BACKUP_ALLOW_LOCAL": allow_local,
            "BACKUP_AGE_RECIPIENT": recipient,
            "BACKUP_REMOTE": f"local:{tmp_path}",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert message in result.stderr
