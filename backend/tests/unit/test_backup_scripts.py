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
    # Premier jour sauvegardé de chaque semaine, puis de chaque mois (ADR 0088) ; les
    # sept plus récentes forment le plancher.
    recent = [f"2026-10-{day:02d}-0215" for day in range(11, 18)]
    names = _names(
        *recent,
        "2026-10-05-0215",  # lundi, premier de sa semaine, 12 jours : gardée
        "2026-10-06-0215",  # mardi de la même semaine : supprimée
        "2026-09-14-0215",  # premier de sa semaine, 33 jours : premier de septembre, gardée
        "2026-09-21-0215",  # premier de sa semaine, 26 jours : gardée
        "2026-09-22-0215",  # même semaine : supprimée
        "2025-11-01-0215",  # premier de novembre, moins d'un an : gardée
        "2025-10-01-0215",  # premier d'octobre, plus d'un an : supprimée
    )
    assert retention.to_delete(names, date(2026, 10, 17)) == _names(
        "2025-10-01-0215", "2026-09-22-0215", "2026-10-06-0215"
    )


def test_only_the_last_backup_of_a_kept_day_survives() -> None:
    retention = _load("backup_retention")
    recent = [f"2026-10-{day:02d}-0215" for day in range(11, 18)]
    names = _names("2026-10-04-0215", "2026-10-04-1830", *recent)
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


# ----------------------------------------------- rétention, constats de la revue (P2.15)


def test_an_orphan_checksum_is_never_a_reason_to_keep_or_delete() -> None:
    """Un `.sha256` sans son dump ne représente aucun jour, et on ne le touche pas."""
    retention = _load("backup_retention")
    names = [*_names("2026-10-16-0215"), "coges-2026-08-03-0215.dump.age.sha256"]
    assert retention.to_delete(names, date(2026, 10, 17)) == []


def test_the_first_backup_of_a_week_without_sunday_is_kept() -> None:
    """Semaine du 28 sept. au 4 oct. sans dimanche (panne) : le premier de la semaine reste."""
    retention = _load("backup_retention")
    names = _names(
        "2026-09-29-0215", "2026-09-30-0215", *(f"2026-10-{d:02d}-0215" for d in range(11, 18))
    )
    assert retention.to_delete(names, date(2026, 10, 17)) == _names("2026-09-30-0215")


def test_the_first_backup_of_a_month_without_the_first_is_kept() -> None:
    retention = _load("backup_retention")
    names = _names(
        "2026-03-02-0215", "2026-03-03-0215", *(f"2026-10-{d:02d}-0215" for d in range(11, 18))
    )
    assert retention.to_delete(names, date(2026, 10, 17)) == _names("2026-03-03-0215")


def test_the_latest_backups_survive_even_when_the_last_week_is_empty() -> None:
    """Sauvegarde en panne depuis trois semaines : jamais moins des 7 plus récentes."""
    retention = _load("backup_retention")
    old = [f"2026-09-{d:02d}-0215" for d in range(14, 26)]  # 12 jours, tous de plus de 21 j
    kept = retention.to_delete(_names(*old), date(2026, 10, 17))
    for stamp in old[-7:]:
        assert f"coges-{stamp}.dump.age" not in kept, f"{stamp} supprimée alors que plus récente"


# ----------------------------------------------------- backup.sh, constats de la revue (P2.16)

_STUBS = {
    "pg_dump": """#!/usr/bin/env bash
if [[ "${1:-}" == --version ]]; then echo "pg_dump (PostgreSQL) 16.4"; exit 0; fi
head -c "${FAKE_DUMP_SIZE:-1000}" /dev/zero
""",
    "age": """#!/usr/bin/env bash
while [[ $# -gt 0 ]]; do [[ "$1" == --output ]] && out=$2; shift; done
cat >"$out"
""",
    # Un distant « fake:dossier » rangé dans $FAKE_REMOTE_ROOT/dossier.
    "lsjson.py": """import json
import os
import sys

path = sys.argv[1]
names = sorted(os.listdir(path)) if os.path.isdir(path) else [os.path.basename(path)]
folder = path if os.path.isdir(path) else os.path.dirname(path)
sizes = [{"Name": n, "Size": os.path.getsize(os.path.join(folder, n))} for n in names]
print(json.dumps(sizes))
""",
    "rclone": """#!/usr/bin/env bash
local_path() { echo "$FAKE_REMOTE_ROOT/${1#fake:}"; }
cmd=$1; shift
args=(); for a in "$@"; do [[ "$a" == --* ]] || args+=("$a"); done
case "$cmd" in
  lsjson)
    p=$(local_path "${args[0]}")
    [[ -e "$p" ]] || { echo "directory not found" >&2; exit 3; }
    python3 "$(dirname "$0")/lsjson.py" "$p" ;;
  copyto) dst=$(local_path "${args[1]}"); mkdir -p "$(dirname "$dst")"; cp "${args[0]}" "$dst" ;;
  cat) cat "$(local_path "${args[0]}")" ;;
  *) exit 9 ;;
esac
""",
}


def _run_backup(
    tmp_path: Path, *, size: int, ratio: str | None = None
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in _STUBS.items():
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_DATABASE_URL": "postgresql://coges_backup@localhost/coges",
        "BACKUP_ALLOW_LOCAL": "1",
        "BACKUP_AGE_RECIPIENT": "age1testrecipient",
        "BACKUP_REMOTE": "fake:sauvegardes/prod",
        "FAKE_REMOTE_ROOT": str(tmp_path / "remote"),
        "FAKE_DUMP_SIZE": str(size),
    }
    if ratio is not None:
        env["BACKUP_MIN_RATIO"] = ratio
    return subprocess.run(
        ["bash", str(SCRIPTS / "backup.sh")], env=env, capture_output=True, text=True, check=False
    )


def _remote_dump(tmp_path: Path, stamp: str, size: int, *, suspect: bool = False) -> None:
    folder = tmp_path / "remote" / "sauvegardes" / "prod"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"coges-{stamp}.dump.age"
    (folder / name).write_bytes(b"\0" * size)
    (folder / f"{name}.sha256").write_text("x", encoding="utf-8")
    if suspect:
        (folder / f"{name}.suspect").write_text("trop petite", encoding="utf-8")


def test_the_first_backup_on_an_empty_remote_succeeds(tmp_path: Path) -> None:
    result = _run_backup(tmp_path, size=1000)
    assert result.returncode == 0, result.stderr


def test_a_suspect_backup_is_never_the_reference(tmp_path: Path) -> None:
    """Valide de 1 000, suspecte de 100 : un dump de 120 se compare à 1 000, et échoue."""
    _remote_dump(tmp_path, "2026-10-15-0215", 1000)
    _remote_dump(tmp_path, "2026-10-16-0215", 100, suspect=True)
    result = _run_backup(tmp_path, size=120)
    assert result.returncode != 0, "comparé à la sauvegarde suspecte, le dump tronqué passe"


def test_a_too_small_backup_is_marked_suspect(tmp_path: Path) -> None:
    _remote_dump(tmp_path, "2026-10-15-0215", 1000)
    result = _run_backup(tmp_path, size=100)
    assert result.returncode != 0
    folder = tmp_path / "remote" / "sauvegardes" / "prod"
    assert any(path.name.endswith(".suspect") for path in folder.iterdir()), (
        "la sauvegarde trop petite deviendrait la référence de la nuit suivante"
    )


def test_the_ratio_is_a_number_never_code(tmp_path: Path) -> None:
    _remote_dump(tmp_path, "2026-10-15-0215", 1000)
    result = _run_backup(tmp_path, size=10, ratio="__import__('sys').exit(0) or 0")
    assert result.returncode != 0, "BACKUP_MIN_RATIO exécuté comme du code Python"
    assert "BACKUP_MIN_RATIO" in result.stderr
