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


# --- Sur site (ADR 0131) : v0.4.0 supprimée dès la pose de v0.4.1 ----------------------

DIGEST_040 = "sha256:" + "4" * 64
DIGEST_041 = "sha256:" + "5" * 64


def _release(module: ModuleType, ident: int, day: int, tag: str, digest: str = "") -> object:
    return module.PackageVersion(
        id=ident,
        created_at=f"2026-11-{day:02d}T10:00:00Z",
        tags=(tag, f"{ident:x}" * 40),
        digest=digest,
    )


def _channel(tmp_path: Path, name: str, version: str, digest: str) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "format": "COGES-CANAL-1",
                "canal": name,
                "version": version,
                "images": {"front": digest, "api": digest, "worker": digest},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_reported_bug_v040_survives_the_tag_v041() -> None:
    """Le cas vu en vrai : v0.4.0 puis v0.4.1, sans production ni canal."""
    cleanup = _module()
    versions = [
        _release(cleanup, 1, 20, "v0.4.0"),
        _release(cleanup, 2, 23, "v0.4.1"),
    ]
    assert cleanup.plan(versions) == []


def test_the_three_highest_releases_stay_older_ones_go() -> None:
    cleanup = _module()
    versions = [
        _release(cleanup, 1, 1, "v0.1.0"),
        _release(cleanup, 2, 2, "v0.2.0"),
        _release(cleanup, 3, 3, "v0.3.0"),
        _release(cleanup, 4, 4, "v0.4.0"),
        _release(cleanup, 5, 5, "v0.4.1"),
    ]
    assert cleanup.plan(versions) == [1, 2]


def test_releases_are_ranked_by_number_not_by_date() -> None:
    """v0.4.0 reconstruite après v0.4.1 : c'est v0.3.0, la plus basse, qui part."""
    cleanup = _module()
    versions = [
        _release(cleanup, 1, 1, "v0.2.0"),
        _release(cleanup, 2, 2, "v0.3.0"),
        _release(cleanup, 3, 3, "v0.4.1"),
        _release(cleanup, 4, 24, "v0.4.0"),
        _release(cleanup, 5, 25, "v0.10.0"),
    ]
    assert cleanup.plan(versions) == [1, 2]


def test_a_prerelease_ranks_below_its_release() -> None:
    cleanup = _module()
    versions = [
        _release(cleanup, 1, 1, "v1.0.0"),
        _release(cleanup, 2, 2, "v1.0.0-rc.1"),
        _release(cleanup, 3, 3, "v0.9.0"),
        _release(cleanup, 4, 4, "v0.8.0"),
    ]
    assert cleanup.plan(versions) == [4]


def test_a_version_cited_by_a_channel_is_never_deleted(tmp_path: Path) -> None:
    """stable.json reste sur une vieille version : ni ses étiquettes ni ses digests ne partent."""
    cleanup = _module()
    channels = cleanup.read_channels([_channel(tmp_path, "stable", "v0.1.0", DIGEST_040)])
    versions = [
        _release(cleanup, 1, 1, "v0.1.0", digest=DIGEST_040),
        _release(cleanup, 2, 2, "v0.2.0"),
        _release(cleanup, 3, 3, "v0.3.0"),
        _release(cleanup, 4, 4, "v0.4.0"),
        _release(cleanup, 5, 5, "v0.4.1"),
    ]
    assert cleanup.plan(versions, channels=channels) == [2]


def test_a_channel_digest_protects_a_version_whose_tag_moved(tmp_path: Path) -> None:
    """Les PC tirent par digest : l'image citée reste même si son étiquette n'y est plus."""
    cleanup = _module()
    channels = cleanup.read_channels([_channel(tmp_path, "test", "v0.0.9", DIGEST_041)])
    orphan = cleanup.PackageVersion(
        id=9, created_at="2026-11-01T10:00:00Z", tags=("a" * 40,), digest=DIGEST_041
    )
    newer = cleanup.PackageVersion(id=10, created_at="2026-11-02T10:00:00Z", tags=("b" * 40,))
    assert cleanup.plan([orphan, newer], channels=channels) == []


def test_both_channels_are_honoured(tmp_path: Path) -> None:
    cleanup = _module()
    channels = cleanup.read_channels(
        [
            _channel(tmp_path, "stable", "v0.1.0", DIGEST_040),
            _channel(tmp_path, "test", "v0.2.0", DIGEST_041),
        ]
    )
    versions = [
        _release(cleanup, 1, 1, "v0.1.0"),
        _release(cleanup, 2, 2, "v0.2.0"),
        _release(cleanup, 3, 3, "v0.2.5"),
        _release(cleanup, 4, 4, "v0.3.0"),
        _release(cleanup, 5, 5, "v0.4.0"),
        _release(cleanup, 6, 6, "v0.4.1"),
    ]
    assert cleanup.plan(versions, channels=channels) == [3]


def test_sha_preprods_keep_the_current_rule_next_to_releases() -> None:
    """Des SHA seuls : la plus récente reste ; les vX.Y.Z ne lui prennent pas sa place."""
    cleanup = _module()
    versions = [
        _release(cleanup, 1, 1, "v0.4.0"),
        cleanup.PackageVersion(id=2, created_at="2026-11-02T10:00:00Z", tags=("c" * 12,)),
        cleanup.PackageVersion(id=3, created_at="2026-11-03T10:00:00Z", tags=("d" * 12,)),
        _release(cleanup, 4, 4, "v0.4.1"),
    ]
    assert cleanup.plan(versions) == [2]


def test_production_does_not_take_one_of_the_three_release_places() -> None:
    """Production v0.2.0 protégée par son étiquette ; les trois plus hautes restent aussi."""
    cleanup = _module()
    versions = [
        cleanup.PackageVersion(
            id=1, created_at="2026-11-01T10:00:00Z", tags=("v0.1.0", "production-previous")
        ),
        cleanup.PackageVersion(
            id=2, created_at="2026-11-02T10:00:00Z", tags=("v0.2.0", "production")
        ),
        _release(cleanup, 3, 3, "v0.3.0"),
        _release(cleanup, 4, 4, "v0.4.0"),
        _release(cleanup, 5, 5, "v0.4.1"),
    ]
    assert cleanup.plan(versions) == []


def test_a_missing_channel_protects_nothing(tmp_path: Path) -> None:
    cleanup = _module()
    channels = cleanup.read_channels([tmp_path / "stable.json"])
    assert channels.tags == frozenset() and channels.digests == frozenset()


@pytest.mark.parametrize(
    "content",
    [
        "{pas du json",
        json.dumps({"format": "AUTRE", "version": "v0.4.1", "images": {"api": DIGEST_041}}),
        json.dumps({"format": "COGES-CANAL-1", "version": "0.4.1", "images": {"api": DIGEST_041}}),
        json.dumps({"format": "COGES-CANAL-1", "version": "v0.4.1", "images": {}}),
        json.dumps({"format": "COGES-CANAL-1", "version": "v0.4.1", "images": {"api": "abc"}}),
        json.dumps(["COGES-CANAL-1"]),
    ],
)
def test_an_unreadable_channel_deletes_nothing(
    tmp_path: Path,
    content: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cleanup = _module()
    broken = tmp_path / "stable.json"
    broken.write_text(content, encoding="utf-8")
    with pytest.raises(cleanup.ChannelError):
        cleanup.read_channels([broken])

    pages = json.dumps(
        [
            {
                "id": ident,
                "created_at": f"2026-10-0{ident}T10:00:00Z",
                "name": "",
                "metadata": {"container": {"tags": [f"{ident}" * 12]}},
            }
            for ident in (1, 2, 3)
        ]
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(pages))
    assert cleanup.main(["plan", "--channel", str(broken)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "", "un identifiant écrit serait supprimé par le job"
    assert "rien n'est supprimé" in captured.err


def test_the_cli_reads_digests_and_channels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """La forme réelle de l'API : le digest est dans `name`."""

    def item(ident: int, day: int, tags: list[str], digest: str) -> dict[str, object]:
        return {
            "id": ident,
            "name": digest,
            "created_at": f"2026-11-{day:02d}T10:00:00Z",
            "metadata": {"package_type": "container", "container": {"tags": tags}},
        }

    pages = json.dumps(
        [
            item(1, 1, ["a" * 40], DIGEST_040),
            item(2, 2, ["b" * 40], "sha256:" + "6" * 64),
            item(3, 3, ["c" * 40], "sha256:" + "7" * 64),
        ]
    )
    channel = _channel(tmp_path, "stable", "v0.4.0", DIGEST_040)
    monkeypatch.setattr("sys.stdin", io.StringIO(pages))
    assert _module().main(["plan", "--channel", str(channel)]) == 0
    assert capsys.readouterr().out.strip() == "2"


def test_the_onprem_channel_files_on_this_branch_are_readable() -> None:
    """Les canaux versionnés passent la lecture du job (sinon le ménage s'arrêterait)."""
    cleanup = _module()
    folder = SCRIPT.parents[2] / "deploy" / "onprem" / "canal"
    cleanup.read_channels([folder / "stable.json", folder / "test.json"])
