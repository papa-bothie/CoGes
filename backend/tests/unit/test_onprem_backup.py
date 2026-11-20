"""Sauvegarde sur site (ADR 0127) : chiffrement, copie fidèle des contrôles, compose."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import re
import sys
import tracemalloc
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

REPO = Path(__file__).resolve().parents[3]
ONPREM = REPO / "deploy" / "onprem"
TOOLS = ONPREM / "sauvegarde"


def _load(path: Path, name: str | None = None) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name or path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


coffre = _load(TOOLS / "coffre.py", "onprem_coffre")
check = _load(ONPREM / "check_onprem_env.py", "onprem_check_env_backup")


def _pair() -> tuple[Any, Any]:
    key = X25519PrivateKey.generate()
    return key, key.public_key()


def _seal(data: bytes, public: Any, chunk: int = 64) -> bytes:
    out = io.BytesIO()
    coffre.encrypt(io.BytesIO(data), out, public, chunk=chunk)
    return out.getvalue()


def _open(sealed: bytes, private: Any) -> bytes:
    out = io.BytesIO()
    coffre.decrypt(io.BytesIO(sealed), out, private)
    return out.getvalue()


# ------------------------------------------------------------------ chiffrement


@pytest.mark.parametrize("size", [0, 1, 63, 64, 65, 128, 1000])
def test_round_trip_whatever_the_size(size: int) -> None:
    private, public = _pair()
    data = bytes(range(256)) * (size // 256 + 1)
    data = data[:size]
    sealed = _seal(data, public)
    assert size < 64 or data not in sealed
    assert _open(sealed, private) == data


def test_the_digest_returned_is_the_one_of_the_plain_dump() -> None:
    private, public = _pair()
    data = b"pg_dump" * 100
    digest = coffre.decrypt(io.BytesIO(_seal(data, public)), None, private)
    assert digest == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    "position", [0, 13, 13 + 32, 13 + 48, coffre.HEADER, coffre.HEADER + 70, -1]
)
def test_one_modified_byte_is_refused(position: int) -> None:
    private, public = _pair()
    sealed = bytearray(_seal(b"x" * 200, public))
    sealed[position] ^= 0x01
    with pytest.raises(coffre.CoffreError):
        _open(bytes(sealed), private)


def test_the_wrong_private_key_is_refused_with_a_clear_message() -> None:
    _private, public = _pair()
    other, _ = _pair()
    with pytest.raises(coffre.CoffreError, match="mauvaise clé privée"):
        _open(_seal(b"donnees" * 50, public), other)


@pytest.mark.parametrize("cut", [1, 16, 64 + 16, 2 * (64 + 16)])
def test_a_truncated_file_is_refused(cut: int) -> None:
    private, public = _pair()
    sealed = _seal(b"y" * 300, public)
    with pytest.raises(coffre.CoffreError):
        _open(sealed[:-cut], private)


def test_a_file_cut_exactly_on_a_block_boundary_is_refused() -> None:
    """Le dernier bloc retiré en entier : l'avant-dernier n'a pas le drapeau de fin."""
    private, public = _pair()
    sealed = _seal(b"z" * 256, public)  # 4 blocs pleins + 1 bloc final vide
    with pytest.raises(coffre.CoffreError, match="coupée"):
        _open(sealed[: -coffre.TAG], private)


def test_appended_or_reordered_blocks_are_refused() -> None:
    private, public = _pair()
    sealed = _seal(b"w" * 200, public)
    with pytest.raises(coffre.CoffreError):
        _open(sealed + b"\0" * 80, private)
    block = 64 + coffre.TAG
    header, body = sealed[: coffre.HEADER], sealed[coffre.HEADER :]
    swapped = header + body[block : 2 * block] + body[:block] + body[2 * block :]
    with pytest.raises(coffre.CoffreError):
        _open(swapped, private)


def test_not_a_backup_is_refused() -> None:
    private, _ = _pair()
    with pytest.raises(coffre.CoffreError, match="pas une sauvegarde"):
        _open(b"PGDMP" + b"\0" * 200, private)


def test_a_big_file_goes_by_blocks_with_bounded_memory(tmp_path: Path) -> None:
    private, public = _pair()
    plain = tmp_path / "gros.dump"
    with plain.open("wb") as handle:
        for index in range(48):
            handle.write(bytes([index]) * (1024 * 1024))
    sealed, back = tmp_path / "gros.coges", tmp_path / "relu.dump"
    tracemalloc.start()
    with plain.open("rb") as source, sealed.open("wb") as target:
        coffre.encrypt(source, target, public)
    with sealed.open("rb") as source, back.open("wb") as target:
        coffre.decrypt(source, target, private)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 8 * 1024 * 1024, f"pic mémoire {peak} o pour 48 Mo"
    assert hashlib.sha256(back.read_bytes()).digest() == hashlib.sha256(plain.read_bytes()).digest()


def test_structure_check_without_the_key() -> None:
    _private, public = _pair()
    sealed = _seal(b"v" * 300, public)
    coffre.check_structure(io.BytesIO(sealed), len(sealed))
    cut = sealed[: coffre.HEADER + 64 + coffre.TAG + 5]
    with pytest.raises(coffre.CoffreError):
        coffre.check_structure(io.BytesIO(cut), len(cut))


def test_encrypt_command_rereads_and_never_overwrites(tmp_path: Path) -> None:
    private, public = _pair()
    plain = tmp_path / "a.dump"
    plain.write_bytes(b"dump" * 1000)
    target = tmp_path / "a.coges"
    coffre.cmd_encrypt(coffre.encode_public(public), plain, target)
    assert _open(target.read_bytes(), private) == plain.read_bytes()
    assert not (tmp_path / "a.coges.partiel").exists()
    with pytest.raises(FileExistsError):
        coffre.cmd_pair(tmp_path / "a.coges", tmp_path / "b.pub")


def test_pair_command_writes_two_files_once(tmp_path: Path) -> None:
    coffre.cmd_pair(tmp_path / "k.prive", tmp_path / "k.pub")
    private = coffre.read_private((tmp_path / "k.prive").read_text())
    public = coffre.read_public((tmp_path / "k.pub").read_text())
    assert coffre.encode_public(private.public_key()) == coffre.encode_public(public)
    assert (tmp_path / "k.prive").stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        coffre.cmd_pair(tmp_path / "k.prive", tmp_path / "autre.pub")


def test_key_files_accept_a_bom_and_crlf_but_nothing_else() -> None:
    private, _ = _pair()
    text = coffre.encode_private(private)
    assert coffre.read_private("﻿" + text + "\r\n")
    for bad in (
        "",
        text + "\n" + text,
        text.replace("PRIVEE", "PUBLIQUE"),
        "COGES-CLE-PRIVEE-1:abc",
    ):
        with pytest.raises(coffre.CoffreError):
            coffre.read_private(bad)


def test_x25519_matches_rfc7748_so_powershell_and_python_agree() -> None:
    """Même vecteur que les tests Pester de New-CogesKeyPair (RFC 7748, § 6.1)."""
    alice = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
    public = X25519PrivateKey.from_private_bytes(alice).public_key()
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert raw.hex() == "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
    pester = (ONPREM / "windows" / "tests" / "CoGes.Backup.Tests.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert alice.hex() in pester and raw.hex() in pester
    encoded = coffre.PUBLIC_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert coffre.encode_public(public) == encoded


# ------------------------------------------------------------------ copie fidèle


def test_the_restore_checks_are_a_faithful_copy_of_the_production_ones() -> None:
    """verify_restore.py de deploy/scripts/ et sa copie livrée sur site : identiques à
    l'octet près. Un changement de la production sans la copie fait échouer la CI."""
    production = (REPO / "deploy" / "scripts" / "verify_restore.py").read_bytes()
    assert (TOOLS / "verify_restore.py").read_bytes() == production


def test_the_on_site_manifest_counts_with_the_production_query() -> None:
    base = (TOOLS / "base.py").read_text(encoding="utf-8")
    assert "verify_restore.manifest_query()" in base
    assert "verify_restore.verify(" in base


def test_the_copy_can_be_imported_where_the_compose_mounts_it() -> None:
    """verify_restore lit parents[2] à l'import : le montage doit en avoir trois."""
    compose = yaml.safe_load((ONPREM / "docker-compose.yml").read_text(encoding="utf-8"))
    for name in ("sauvegarde-pg", "sauvegarde-py"):
        mount = next(
            v for v in compose["services"][name]["volumes"] if v.startswith("./sauvegarde:")
        )
        target = mount.split(":")[1]
        assert len(Path(target).parents) >= 3, target


# ------------------------------------------------------------------ compose et contrôle


def _compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (ONPREM / "docker-compose.yml").read_text(encoding="utf-8")
    )
    return data


@pytest.mark.parametrize("name", ["sauvegarde-pg", "sauvegarde-py"])
def test_backup_services_are_tools_without_port_secret_or_internet(name: str) -> None:
    service = _compose()["services"][name]
    assert service["profiles"] == ["tools"]
    assert service["network_mode"] == "service:postgres"
    assert "ports" not in service and "networks" not in service
    assert "environment" not in service
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert "sauvegarde-travail:/travail" in service["volumes"]
    assert service["restart"] == "no"


def test_the_plain_dump_volume_is_declared_and_used_by_the_backup_services_only() -> None:
    compose = _compose()
    assert "sauvegarde-travail" in compose["volumes"]
    users = {
        name
        for name, service in compose["services"].items()
        if any("sauvegarde-travail" in str(v) for v in service.get("volumes", []))
    }
    assert users == {"sauvegarde-pg", "sauvegarde-py"}


def test_the_backup_postgres_image_is_the_database_one() -> None:
    services = _compose()["services"]
    assert services["sauvegarde-pg"]["image"] == services["postgres"]["image"]
    assert re.search(r"/worker:\$\{COGES_IMAGE_TAG", services["sauvegarde-py"]["image"])


def _rendered(**services: dict[str, Any]) -> dict[str, Any]:
    return {"services": services}


def test_the_superuser_password_never_leaves_the_postgres_service() -> None:
    ok = _rendered(postgres={"environment": {"POSTGRES_PASSWORD": "x" * 20}})
    assert check.rendered_violations(ok, source="r") == []
    for key in ("POSTGRES_PASSWORD", "PGPASSWORD", "COGES_POSTGRES_PASSWORD"):
        bad = _rendered(api={"environment": {key: "x" * 20}})
        assert any("superutilisateur" in v for v in check.rendered_violations(bad, source="r")), key


def test_only_backup_services_share_the_network_of_postgres() -> None:
    good = {"profiles": ["tools"], "network_mode": "service:postgres"}
    assert check.rendered_violations(_rendered(**{"sauvegarde-pg": good}), source="r") == []
    stranger = _rendered(api={"network_mode": "service:postgres"})
    assert any("partage le réseau" in v for v in check.rendered_violations(stranger, source="r"))
    other = _rendered(**{"sauvegarde-py": {"profiles": ["tools"], "network_mode": "service:redis"}})
    assert check.rendered_violations(other, source="r")
    continuous = _rendered(**{"sauvegarde-pg": {"network_mode": "service:postgres"}})
    assert any("profil tools" in v for v in check.rendered_violations(continuous, source="r"))


def test_backup_services_receive_no_password_nor_dsn() -> None:
    for env in (
        {"PGPASSWORD": "secret-secret"},
        {"COGES_DATABASE_URL_APP": "postgresql+psycopg://coges_app:x@postgres:5432/coges"},
        {"COGES_JWT_SECRET": "z" * 64},
        {"ANYTHING": "postgresql://postgres@127.0.0.1/coges"},
    ):
        service = {"profiles": ["tools"], "network_mode": "service:postgres", "environment": env}
        assert check.rendered_violations(_rendered(**{"sauvegarde-py": service}), source="r"), env
