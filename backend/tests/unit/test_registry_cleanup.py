"""Le registre d'images : jamais la production supprimée, jamais une étiquette repoussée.

Prompt 21, P1.2 ; ADR 0087. L'ancien nettoyage gardait « 5 versions » tous
environnements confondus : cinq déploiements de préproduction supprimaient l'image de
production, et le retour arrière comme la reconstruction du VPS échouaient.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "scripts" / "registry_cleanup.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("registry_cleanup", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` relit son module dans `sys.modules`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _version(module: ModuleType, ident: int, day: int, *tags: str) -> object:
    return module.PackageVersion(id=ident, created_at=f"2026-10-{day:02d}T10:00:00Z", tags=tags)


def test_five_recent_preprods_never_remove_an_old_production() -> None:
    cleanup = _module()
    versions = [
        _version(cleanup, 1, 1, "v1.0.0", "a" * 40, "production"),
        _version(cleanup, 2, 2, "v0.9.0", "b" * 40, "production-previous"),
        *[_version(cleanup, 10 + day, 10 + day, f"{day:x}" * 12) for day in range(5)],
    ]

    doomed = cleanup.plan(versions)

    assert 1 not in doomed and 2 not in doomed, "la production ou la précédente part"
    assert doomed == [10, 11, 12, 13], "seule la préproduction la plus récente reste"


def test_untagged_versions_are_never_deleted() -> None:
    cleanup = _module()
    versions = [
        _version(cleanup, 1, 1),
        _version(cleanup, 2, 2, "c" * 12),
        _version(cleanup, 3, 3, "d" * 12),
    ]
    assert cleanup.plan(versions) == [2]


def test_nothing_to_delete_when_only_protected_and_latest_remain() -> None:
    cleanup = _module()
    versions = [
        _version(cleanup, 1, 1, "v1.0.0", "production"),
        _version(cleanup, 2, 2, "v1.1.0"),
    ]
    assert cleanup.plan(versions) == []


def test_an_existing_tag_with_other_code_is_refused() -> None:
    cleanup = _module()
    with pytest.raises(cleanup.RefusedError):
        cleanup.decide("v1.2.0", version_digest="sha256:aaa", sha_digest="sha256:bbb")
    with pytest.raises(cleanup.RefusedError):
        cleanup.decide("v1.2.0", version_digest="sha256:aaa", sha_digest="")


def test_an_existing_tag_of_the_same_commit_is_reused() -> None:
    """Préproduction puis production de la même version : la même image, sans rebâtir."""
    cleanup = _module()
    assert cleanup.decide("v1.2.0", version_digest="sha256:aaa", sha_digest="sha256:aaa") == (
        "reuse"
    )


def test_a_new_tag_or_a_sha_is_built() -> None:
    cleanup = _module()
    assert cleanup.decide("v1.3.0", version_digest="", sha_digest="") == "build"
    assert cleanup.decide("0123456789ab", version_digest="sha256:x", sha_digest="") == "build"


def test_the_cli_refuses_with_status_1(capsys: pytest.CaptureFixture[str]) -> None:
    cleanup = _module()
    status = cleanup.main(
        ["decide", "--version", "v1.2.0", "--version-digest", "sha256:a", "--sha-digest", "x"]
    )
    assert status == 1
    assert "existe déjà" in capsys.readouterr().err


def test_the_cli_reads_paginated_api_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def item(ident: int, day: int, tags: list[str]) -> dict[str, object]:
        return {
            "id": ident,
            "created_at": f"2026-10-{day:02d}T10:00:00Z",
            "metadata": {"package_type": "container", "container": {"tags": tags}},
        }

    pages = (
        json.dumps([item(1, 1, ["v1.0.0", "production"]), item(2, 2, ["e" * 12])])
        + "\n"
        + json.dumps([item(3, 3, ["f" * 12]), item(4, 4, [])])
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(pages))
    assert _module().main(["plan"]) == 0
    assert capsys.readouterr().out.strip() == "2"
