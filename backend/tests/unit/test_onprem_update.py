"""Mises à jour sur site (ADR 0128) : canal, empreinte du programme, registre, noms des bases."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import threading
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
ONPREM = REPO / "deploy" / "onprem"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


publier = _load(ONPREM / "canal" / "publier.py", "onprem_publier")

DIGESTS = {
    name: "sha256:" + letter * 64 for name, letter in zip(publier.IMAGES, "abc", strict=True)
}


def _archive(
    path: Path,
    *,
    prefix: str = "CoGes-0.4.0",
    compression: int = zipfile.ZIP_DEFLATED,
    extra: dict[str, str] | None = None,
    without: tuple[str, ...] = (),
) -> Path:
    """Une archive au format de GitHub, faite du vrai dossier deploy/onprem."""
    with zipfile.ZipFile(path, "w", compression=compression) as zipped:
        for file in sorted(ONPREM.rglob("*")):
            relative = file.relative_to(ONPREM).as_posix()
            if file.is_dir() or "__pycache__" in relative or relative in without:
                continue
            zipped.writestr(f"{prefix}/deploy/onprem/{relative}", file.read_bytes())
        for name, text in (extra or {}).items():
            zipped.writestr(f"{prefix}/deploy/onprem/{name}", text)
        zipped.writestr(f"{prefix}/README.md", "hors de deploy/onprem")
    return path


def _canal(**changes: Any) -> dict[str, Any]:
    data = {
        "format": "COGES-CANAL-1",
        "canal": "stable",
        "version": "v0.4.0",
        "publiee_le": "2026-11-22",
        "depuis_minimum": "v0.3.0",
        "images": dict(DIGESTS),
        "programme": {"sha256": "d" * 64, "fichiers": 20},
        "docker_desktop_minimum": None,
        "note": "Corrige l'impression du ticket.",
        "signature": None,
    }
    data.update(changes)
    return data


# ---------------------------------------------------------------------------- empreinte


def test_programme_digest_ignores_zip_compression_and_folder_name(tmp_path: Path) -> None:
    one = _archive(tmp_path / "a.zip")
    two = _archive(tmp_path / "b.zip", prefix="CoGes-autre", compression=zipfile.ZIP_STORED)
    assert hashlib.sha256(one.read_bytes()).digest() != hashlib.sha256(two.read_bytes()).digest()
    assert publier.programme_digest(one) == publier.programme_digest(two)


def test_programme_digest_follows_content_and_counts_only_deploy_onprem(tmp_path: Path) -> None:
    base, count = publier.programme_digest(_archive(tmp_path / "a.zip"))
    changed, more = publier.programme_digest(
        _archive(tmp_path / "b.zip", extra={"canal/stable.json": "{}"})
    )
    cached, same = publier.programme_digest(
        _archive(tmp_path / "c.zip", extra={"sauvegarde/__pycache__/x.pyc": "x"})
    )
    assert changed != base and more == count + 1
    assert (cached, same) == (base, count)
    expected = sum(
        1 for file in ONPREM.rglob("*") if file.is_file() and "__pycache__" not in file.as_posix()
    )
    assert count == expected


def test_programme_digest_is_the_documented_listing(tmp_path: Path) -> None:
    archive = tmp_path / "petit.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for name in publier.REQUIRED:
            zipped.writestr(f"CoGes-1/deploy/onprem/{name}", name)
    lines = sorted(
        f"{hashlib.sha256(name.encode()).hexdigest()}  {name}\n" for name in publier.REQUIRED
    )
    lines.sort(key=lambda line: line.split("  ", 1)[1])
    expected = hashlib.sha256("".join(lines).encode()).hexdigest()
    assert publier.programme_digest(archive) == (expected, 3)


def test_programme_without_the_update_script_is_refused(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "ancien.zip", without=("windows/mise-a-jour.ps1",))
    with pytest.raises(publier.CanalError, match="ne sait pas se mettre à jour seul"):
        publier.programme_digest(archive)


def test_path_climbing_out_is_refused(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "piege.zip", extra={"windows/../../x": "x"})
    with pytest.raises(publier.CanalError, match="chemin refusé"):
        publier.programme_digest(archive)


# ---------------------------------------------------------------------------- canal


def test_a_complete_channel_has_no_problem() -> None:
    assert publier.canal_problems(_canal()) == []


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"version": "latest"}, "version : vX.Y.Z"),
        ({"depuis_minimum": "v0.5.0"}, "depuis_minimum est plus récent"),
        ({"canal": "beta"}, "canal 'beta' inconnu"),
        ({"format": "AUTRE"}, "format"),
        ({"publiee_le": "22/11/2026"}, "publiee_le"),
        ({"images": {"front": DIGESTS["front"], "api": DIGESTS["api"]}}, "images : front"),
        ({"images": {**DIGESTS, "api": "sha256:court"}}, "images.api"),
        ({"programme": {"sha256": "d" * 64, "fichiers": 0}}, "programme"),
        ({"docker_desktop_minimum": "4.30"}, "docker_desktop_minimum"),
        ({"note": " "}, "note"),
        ({"signature": "abc"}, "signature : réservée"),
    ],
)
def test_channel_problems(changes: dict[str, Any], expected: str) -> None:
    assert any(expected in problem for problem in publier.canal_problems(_canal(**changes)))


def test_missing_field_is_named() -> None:
    data = _canal()
    del data["depuis_minimum"]
    assert publier.canal_problems(data) == ["champs absents : depuis_minimum"]


def test_versions_compare_as_numbers() -> None:
    assert publier.version_key("v0.10.0") > publier.version_key("v0.9.9")
    with pytest.raises(publier.CanalError):
        publier.version_key("0.4.0")


# ---------------------------------------------------------------------- registre (faux, en local)


class _Registry(BaseHTTPRequestHandler):
    """Un registre qui exige un jeton anonyme, comme ghcr.io."""

    tags: dict[str, str] = {}
    seen: list[str] = []

    def log_message(self, *_: object) -> None:  # silence
        return

    def do_GET(self) -> None:
        self.seen.append(f"GET {self.path}")
        if self.path.startswith("/token?"):
            body = json.dumps({"token": "anonyme"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_HEAD(self) -> None:
        self.seen.append(f"HEAD {self.path} {self.headers.get('Authorization')}")
        if self.headers.get("Authorization") != "Bearer anonyme":
            host = self.headers["Host"]
            self.send_response(401)
            self.send_header(
                "WWW-Authenticate",
                f'Bearer realm="http://{host}/token",service="essai",scope="repository:x:pull"',
            )
            self.end_headers()
            return
        assert "application/vnd.oci.image.index.v1+json" in self.headers.get("Accept", "")
        digest = self.tags.get(self.path)
        if digest is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Docker-Content-Digest", digest)
        self.end_headers()


@pytest.fixture
def registry() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Registry)
    _Registry.tags = {
        f"/v2/coges/{name}/manifests/v0.4.0": digest for name, digest in DIGESTS.items()
    }
    _Registry.seen = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"127.0.0.1:{server.server_address[1]}/coges"
    finally:
        server.shutdown()


def test_registry_digest_with_an_anonymous_token(registry: str) -> None:
    assert publier.registry_digest(registry, "api", "v0.4.0") == DIGESTS["api"]
    assert _Registry.seen[0].endswith(" None")
    assert any(line.startswith("GET /token?") for line in _Registry.seen)


def test_unknown_tag_is_refused(registry: str) -> None:
    with pytest.raises(publier.CanalError, match="n'existe pas"):
        publier.registry_digest(registry, "api", "v9.9.9")


def test_main_writes_the_channel_and_never_goes_back(registry: str, tmp_path: Path) -> None:
    archive = _archive(tmp_path / "v0.4.0.zip")
    output = tmp_path / "test.json"
    args = [
        "--version", "v0.4.0", "--canal", "test", "--depuis-minimum", "v0.3.0",
        "--note", "Essai.", "--registre", registry, "--archive", str(archive),
        "--sortie", str(output), "--date", "2026-11-22",
    ]  # fmt: skip
    assert publier.main(args) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert publier.canal_problems(data) == []
    assert data["images"] == DIGESTS
    assert (data["programme"]["sha256"], data["programme"]["fichiers"]) == publier.programme_digest(
        archive
    )
    assert data["signature"] is None
    assert output.read_text(encoding="utf-8").endswith("}\n")
    # Le canal ne redescend jamais.
    older = [arg if arg != "v0.4.0" else "v0.3.9" for arg in args]
    assert publier.main(older) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["version"] == "v0.4.0"


# ---------------------------------------------------------------------------- base.py (noms)


def test_update_copies_are_not_offered_to_the_cleanup_but_are_droppable() -> None:
    pytest.importorskip("psycopg")
    base = _load(ONPREM / "sauvegarde" / "base.py", "onprem_base_update")
    assert base.UPDATE_COPY.match("coges_avant_maj_20261122_213500")
    assert not base.LISTED.match("coges_avant_maj_20261122_213500")
    for name in (
        "coges_avant_20261122_2135",
        "coges_echec_maj_20261122_213500",
        "coges_apres_maj_20261122_213500",
    ):
        assert base.LISTED.match(name), name
    for refused in ("coges", "postgres", "coges_avant_maj_x", "coges_apres_maj_20261122"):
        assert not any(
            rule.match(refused)
            for rule in (base.SCRATCH, base.KEPT, base.UPDATE_COPY, base.UPDATE_KEPT)
        ), refused
    with pytest.raises(base.BaseError):
        base.cmd_copy("demain")
    with pytest.raises(base.BaseError):
        base.cmd_put_back("20261122_213500", "autre")
