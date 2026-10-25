"""Scripts de la sauvegarde externe (ADR 0084) : rétention, refus de la restauration.

La chaîne complète (dump → chiffrement → restauration → vérification) est prouvée par
`deploy/scripts/backup_chain_check.sh`, joué en CI contre un vrai PostgreSQL. Ici, les
refus : ils doivent tenir avant même de toucher une base.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
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
    (tmp_path / f"{path.name}.manifest.json").write_text(
        '{"pg_dump_version": "18.1", "server_version": "18.1", "tables": {"sales": 3}}\n'
    )
    (tmp_path / "test.key").write_text("AGE-SECRET-KEY-TEST\n")
    return path


def _restore(
    archive: Path,
    target: str,
    *,
    production_host: str | None,
    psql_says: str = "0 0 0 0",
    psql_rights: str = "",
    pg_restore_version: str = "18.1",
    toc: str | None = None,
) -> subprocess.CompletedProcess[str]:
    # Un faux `psql` répond au comptage des objets de la cible (tables, types, fonctions,
    # séquences) et au contrôle des droits sur public, un faux `pg_restore` à `--version` :
    # aucune base requise. Avec `toc`, un faux `age` rend l'archive telle quelle,
    # `pg_restore --list` rend ce sommaire et `--use-list` recopie la liste reçue dans
    # `used.list`, à côté de l'archive.
    bin_dir = archive.parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    used = archive.parent / "used.list"
    (archive.parent / "toc.list").write_text(toc or "")
    fakes = {
        "psql": (
            "#!/bin/sh\n"
            'case "$*" in *has_schema_privilege*) '
            f"printf '%s' '{psql_rights}' ;; *) echo '{psql_says}' ;; esac\n"
        ),
        "pg_restore": (
            "#!/bin/sh\n"
            'case "$1" in\n'
            f"  --version) echo 'pg_restore (PostgreSQL) {pg_restore_version}' ;;\n"
            f"  --list) cat >/dev/null; cat '{archive.parent / 'toc.list'}' ;;\n"
            f'  *) cat >/dev/null; for a; do case "$a" in --use-list=*) '
            f"cp \"${{a#--use-list=}}\" '{used}' ;; esac; done ;;\n"
            "esac\n"
        ),
    }
    if toc is not None:
        fakes["age"] = '#!/bin/sh\nfor a; do f="$a"; done\ncat "$f"\n'
    for name, body in fakes.items():
        fake = bin_dir / name
        fake.write_text(body)
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
        archive,
        "postgresql://u@secours.local/db",
        production_host="prod.neon.tech",
        psql_says="12 0 0 0",
    )
    assert result.returncode == 1
    assert "pas vide" in result.stderr


@pytest.mark.parametrize(
    ("counts", "what"),
    [("0 1 0 0", "1 type(s)"), ("0 0 3 0", "3 fonction(s)"), ("0 0 0 2", "2 séquence(s)")],
)
def test_restore_refuses_a_database_left_by_a_failed_attempt(
    archive: Path, counts: str, what: str
) -> None:
    """Un essai interrompu laisse des types ou des fonctions sans aucune table."""
    result = _restore(
        archive,
        "postgresql://u@secours.local/db",
        production_host="prod.neon.tech",
        psql_says=counts,
    )
    assert result.returncode == 1
    assert "pas vide" in result.stderr
    assert what in result.stderr
    assert "recréer" in result.stderr


def test_restore_refuses_when_owners_cannot_create_in_public(archive: Path) -> None:
    result = _restore(
        archive,
        "postgresql://u@secours.local/db",
        production_host="prod.neon.tech",
        psql_rights="coges_auth droits\ncoges_ops droits\n",
    )
    assert result.returncode == 1
    assert "GRANT USAGE, CREATE ON SCHEMA public TO coges_auth, coges_ops;" in result.stderr
    assert "restauration" not in result.stdout


def test_restore_refuses_when_an_owner_role_is_missing(archive: Path) -> None:
    result = _restore(
        archive,
        "postgresql://u@secours.local/db",
        production_host="prod.neon.tech",
        psql_rights="coges_billing absent\n",
    )
    assert result.returncode == 1
    assert "rôle(s) absent(s) de la cible : coges_billing" in result.stderr


NEON_TOC = """;
; Archive created at 2026-10-25 13:27:01 UTC
;
3; 2615 2200 SCHEMA - public pg_database_owner
220; 1259 16390 TABLE public sales coges_owner
5001; 0 0 ACL - SCHEMA public pg_database_owner
5002; 0 0 ACL public TABLE sales coges_owner
5003; 826 16400 DEFAULT ACL public DEFAULT PRIVILEGES FOR SEQUENCES cloud_admin
5004; 826 16401 DEFAULT ACL public DEFAULT PRIVILEGES FOR TABLES cloud_admin
5005; 826 16402 DEFAULT ACL - DEFAULT PRIVILEGES FOR FUNCTIONS neon_superuser
5006; 826 16403 DEFAULT ACL public DEFAULT PRIVILEGES FOR TABLES coges_owner
5007; 0 0 ACL public FUNCTION auth_lookup(p_login text) coges_auth
5008; 0 0 ACL - SCHEMA neon neon_service
"""


def test_restore_excludes_neon_internal_acls_and_keeps_coges_ones(archive: Path) -> None:
    result = _restore(
        archive, "postgresql://u@secours.local/db", production_host="prod.neon.tech", toc=NEON_TOC
    )
    used = (archive.parent / "used.list").read_text()
    for kept in ("5001;", "5002;", "5006;", "5007;", "220;", "3;"):
        assert kept in used
    for excluded in ("5003;", "5004;", "5005;", "5008;"):
        assert excluded not in used
    assert "4 entrée(s) interne(s) à Neon exclue(s)" in result.stdout
    assert "DEFAULT ACL public DEFAULT PRIVILEGES FOR SEQUENCES cloud_admin" in result.stdout
    lines = result.stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if "exclue(s)" in line)
    titles = [line.strip() for line in lines[start + 1 : start + 5]]
    assert "restauration terminée" in lines[start + 5]
    assert len(titles) == 4
    assert not any(title.endswith(("coges_owner", "coges_auth")) for title in titles)


def test_toc_filter_never_excludes_a_coges_role() -> None:
    toc_filter = _load("restore_toc_filter")
    assert not toc_filter.is_neon_acl(
        "1; 826 2 DEFAULT ACL public DEFAULT PRIVILEGES FOR TABLES coges_owner"
    )
    assert not toc_filter.is_neon_acl("1; 0 0 ACL public TABLE neon_like coges_app")
    assert not toc_filter.is_neon_acl("1; 1259 3 TABLE public neon_notes cloud_admin")
    assert toc_filter.is_neon_acl(
        "1; 826 2 DEFAULT ACL public DEFAULT PRIVILEGES FOR TABLES cloud_admin"
    )


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
if [[ "${1:-}" == --version ]]; then
  echo "pg_dump (PostgreSQL) ${FAKE_PG_DUMP_VERSION:-18.1} (Ubuntu 18.1-1.pgdg24.04+1)"; exit 0
fi
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
    # La version du serveur, puis le comptage des tables clés : « table<TAB>lignes ».
    "psql": """#!/usr/bin/env bash
if [[ "$*" == *server_version_num* ]]; then
  printf '%s\\t%s\\n' "${FAKE_SERVER_VERSION_NUM:-180001}" "${FAKE_SERVER_VERSION:-18.1}"
  exit 0
fi
printf 'users\\t3\\nsales\\t12\\n'
""",
    # Les pings Healthchecks, notés au lieu d'être envoyés.
    "curl": """#!/usr/bin/env bash
echo "${@: -1}" >>"$FAKE_PINGS"
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
    tmp_path: Path, *, size: int, ratio: str | None = None, **versions: str
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
        "FAKE_PINGS": str(tmp_path / "pings.log"),
        "BACKUP_PING_URL": "https://hc-ping.invalid/coges",
        **{f"FAKE_{name.upper()}": value for name, value in versions.items()},
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


# ------------------------------------------------- manifeste de comptes (P2.17, ADR 0088)


def test_a_restore_with_fewer_rows_than_the_manifest_fails() -> None:
    verify = _load("verify_restore")
    gaps = verify.manifest_gaps({"sales": 12, "users": 3}, {"sales": 7, "users": 3})
    assert gaps == ["sales : 7 restaurées, 12 au moment de la sauvegarde"]


def test_rows_written_during_the_dump_are_not_a_gap() -> None:
    """Le comptage précède le dump : la base restaurée peut en avoir davantage."""
    verify = _load("verify_restore")
    assert verify.manifest_gaps({"sales": 12}, {"sales": 13}) == []


def test_a_table_missing_from_the_restore_is_a_gap() -> None:
    verify = _load("verify_restore")
    assert verify.manifest_gaps({"debts": 2}, {}) == [
        "debts : 0 restaurées, 2 au moment de la sauvegarde"
    ]


def test_restore_refuses_without_manifest(archive: Path) -> None:
    Path(f"{archive}.manifest.json").unlink()
    result = _restore(archive, "postgresql://u@secours.local/db", production_host="prod.neon.tech")
    assert result.returncode == 1
    assert "manifeste absent" in result.stderr


def test_the_backup_uploads_a_manifest_of_counts(tmp_path: Path) -> None:
    result = _run_backup(tmp_path, size=1000)
    assert result.returncode == 0, result.stderr
    folder = tmp_path / "remote" / "sauvegardes" / "prod"
    manifests = [p for p in folder.iterdir() if p.name.endswith(".manifest.json")]
    assert len(manifests) == 1, "aucun manifeste envoyé avec la sauvegarde"
    assert '"sales": 12' in manifests[0].read_text(encoding="utf-8")


def test_retention_deletes_a_manifest_with_its_dump() -> None:
    retention = _load("backup_retention")
    names = [*_names("2025-10-02-0215"), "coges-2025-10-02-0215.dump.age.manifest.json"]
    names += _names(*(f"2026-10-{day:02d}-0215" for day in range(11, 18)))
    assert "coges-2025-10-02-0215.dump.age.manifest.json" in retention.to_delete(
        names, date(2026, 10, 17)
    )


# ------------------------------------------- version majeure du client (ADR 0095)
#
# La production Neon est en PostgreSQL 18 : un pg_dump 16 refuse de la sauvegarder
# (« aborting because of server version mismatch »). backup.sh le dit avant de dumper,
# en clair, et prévient Healthchecks.


def _pings(tmp_path: Path) -> list[str]:
    log = tmp_path / "pings.log"
    return log.read_text(encoding="utf-8").split() if log.exists() else []


def _manifest(tmp_path: Path) -> dict[str, object]:
    folder = tmp_path / "remote" / "sauvegardes" / "prod"
    (path,) = [p for p in folder.iterdir() if p.name.endswith(".manifest.json")]
    data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_backup_refuses_a_pg_dump_older_than_the_server(tmp_path: Path) -> None:
    result = _run_backup(tmp_path, size=1000, pg_dump_version="16.4", server_version_num="180001")
    assert result.returncode == 1
    assert "pg_dump 16 trop ancien pour un serveur 18" in result.stderr
    assert "installer postgresql-client-18" in result.stderr
    assert _pings(tmp_path) == ["https://hc-ping.invalid/coges/fail"]
    assert not (tmp_path / "remote").exists(), "rien ne doit partir vers le stockage"


def test_a_pg_dump_of_the_server_version_passes(tmp_path: Path) -> None:
    result = _run_backup(tmp_path, size=1000, pg_dump_version="18.1", server_version_num="180001")
    assert result.returncode == 0, result.stderr
    assert _pings(tmp_path) == ["https://hc-ping.invalid/coges"]


def test_a_pg_dump_newer_than_the_server_passes(tmp_path: Path) -> None:
    result = _run_backup(
        tmp_path,
        size=1000,
        pg_dump_version="18.1",
        server_version_num="160010",
        server_version="16.10",
    )
    assert result.returncode == 0, result.stderr


def test_an_unreadable_server_version_fails(tmp_path: Path) -> None:
    result = _run_backup(tmp_path, size=1000, server_version_num="inconnu")
    assert result.returncode == 1
    assert "version du serveur illisible" in result.stderr


def test_the_manifest_records_both_versions(tmp_path: Path) -> None:
    result = _run_backup(tmp_path, size=1000, pg_dump_version="18.1", server_version="18.0")
    assert result.returncode == 0, result.stderr
    manifest = _manifest(tmp_path)
    assert manifest["server_version"] == "18.0"
    assert manifest["pg_dump_version"] == "18.1"
    assert manifest["tables"] == {"sales": 12, "users": 3}


def test_restore_refuses_a_pg_restore_older_than_the_pg_dump(archive: Path) -> None:
    result = _restore(
        archive,
        "postgresql://u@secours.local/db",
        production_host="prod.neon.tech",
        pg_restore_version="16.4",
    )
    assert result.returncode == 1
    assert "pg_restore 16 trop ancien pour une sauvegarde de pg_dump 18" in result.stderr
    assert "installer postgresql-client-18" in result.stderr


def test_restore_accepts_a_pg_restore_of_the_same_major(archive: Path) -> None:
    result = _restore(
        archive,
        "postgresql://u@secours.local/db",
        production_host="prod.neon.tech",
        pg_restore_version="18.0",
    )
    # Le faux psql dit « base vide » ; la suite échoue plus loin (faux age), pas ici.
    assert "trop ancien" not in result.stderr
    assert "base vide" in result.stdout


def test_restore_warns_when_the_manifest_has_no_version(archive: Path) -> None:
    """Sauvegarde antérieure à l'ADR 0095 : on prévient, on ne bloque pas."""
    Path(f"{archive}.manifest.json").write_text('{"tables": {"sales": 3}}\n')
    result = _restore(
        archive,
        "postgresql://u@secours.local/db",
        production_host="prod.neon.tech",
        pg_restore_version="16.4",
    )
    assert "AVERTISSEMENT" in result.stderr
    assert "version de pg_dump inconnue" in result.stderr
    assert "base vide" in result.stdout
