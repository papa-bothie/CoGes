"""Chiffrement des sauvegardes sur site par clé publique (ADR 0127).

Le PC du client n'a que la clé PUBLIQUE : il chiffre, il ne relit pas. La clé privée reste
chez CoGes ; le technicien l'apporte pour restaurer (entrée standard, jamais un argument,
une variable d'environnement ni un fichier copié sur le PC).

Format « COGES-SAUV-1 » (tous les entiers en gros-boutiste) :

    en-tête   = b"COGES-SAUV-1\\0" (13 o) · clé publique éphémère X25519 (32 o)
                · sel (16 o) · taille d'un bloc en clair (4 o)
    clé       = HKDF-SHA256(X25519(éphémère, destinataire), sel,
                            info = b"coges-sauvegarde-v1" · éphémère · destinataire, 32 o)
    blocs     = AES-256-GCM(clé, nonce = n° du bloc (11 o) · drapeau (1 o), bloc, en-tête)
                le drapeau vaut 1 sur le DERNIER bloc seulement (éventuellement vide)

Un octet changé, un bloc retiré, réordonné ou ajouté, un fichier coupé : refusé (le tag
d'un bloc, le numéro dans le nonce, le drapeau de fin). La mémoire reste bornée (un bloc).

Commandes (lancées dans l'image `worker`, qui a `cryptography`) :

    python coffre.py paire --prive FICHIER --publique FICHIER     tirer une paire (technicien)
    python coffre.py publique < clé-privée                        la clé publique d'une privée
    python coffre.py chiffrer --publique CLÉ ENTRÉE SORTIE        chiffre, puis relit et déchiffre
    python coffre.py dechiffrer ENTRÉE SORTIE < clé-privée        déchiffre
    python coffre.py controler ENTRÉE                             structure sans la clé
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import struct
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"COGES-SAUV-1\0"
INFO = b"coges-sauvegarde-v1"
PRIVATE_PREFIX = "COGES-CLE-PRIVEE-1:"
PUBLIC_PREFIX = "COGES-CLE-PUBLIQUE-1:"
CHUNK = 1024 * 1024
TAG = 16
HEADER = len(MAGIC) + 32 + 16 + 4


class CoffreError(Exception):
    """Refus expliqué en français, sans trace technique."""


# ---------------------------------------------------------------------------- clés


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as error:
        raise CoffreError("clé illisible (base64)") from error
    if len(raw) != 32:
        raise CoffreError("clé illisible (32 octets attendus)")
    return raw


def encode_private(key: X25519PrivateKey) -> str:
    raw = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return PRIVATE_PREFIX + _b64(raw)


def encode_public(key: X25519PublicKey) -> str:
    return PUBLIC_PREFIX + _b64(
        key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )


def _one_line(text: str, prefix: str, what: str) -> str:
    lines = [line.strip() for line in text.lstrip("﻿").splitlines() if line.strip()]
    if len(lines) != 1 or not lines[0].startswith(prefix):
        raise CoffreError(f"ce n'est pas une {what} CoGes (une ligne « {prefix}… » attendue)")
    return lines[0][len(prefix) :]


def read_private(text: str) -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(
        _unb64(_one_line(text, PRIVATE_PREFIX, "clé privée"))
    )


def read_public(text: str) -> X25519PublicKey:
    return X25519PublicKey.from_public_bytes(_unb64(_one_line(text, PUBLIC_PREFIX, "clé publique")))


def _derive(shared: bytes, salt: bytes, ephemeral: bytes, recipient: bytes) -> bytes:
    if shared == bytes(32):
        raise CoffreError("clé publique invalide")
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=salt, info=INFO + ephemeral + recipient
    ).derive(shared)


def _nonce(index: int, last: bool) -> bytes:
    if index >= 1 << 88:
        raise CoffreError("fichier trop grand")
    return index.to_bytes(11, "big") + (b"\1" if last else b"\0")


# ---------------------------------------------------------------------------- chiffrer


def _chunks(source: BinaryIO, size: int) -> Iterator[tuple[bytes, bool]]:
    """Les blocs en clair, le dernier marqué (un bloc vide si la taille tombe juste)."""
    current = source.read(size)
    while True:
        following = source.read(size) if len(current) == size else b""
        last = not following
        yield current, last
        if last:
            return
        current = following


def encrypt(
    source: BinaryIO, target: BinaryIO, recipient: X25519PublicKey, *, chunk: int = CHUNK
) -> bytes:
    """Chiffre `source` vers `target` ; rend la clé de contenu (pour la relecture)."""
    ephemeral = X25519PrivateKey.generate()
    ephemeral_raw = ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    recipient_raw = recipient.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    salt = os.urandom(16)
    header = MAGIC + ephemeral_raw + salt + struct.pack(">I", chunk)
    key = _derive(ephemeral.exchange(recipient), salt, ephemeral_raw, recipient_raw)
    aead = AESGCM(key)
    target.write(header)
    for index, (block, last) in enumerate(_chunks(source, chunk)):
        target.write(aead.encrypt(_nonce(index, last), block, header))
    return key


# ---------------------------------------------------------------------------- déchiffrer


def _read_header(source: BinaryIO) -> tuple[bytes, bytes, bytes, int]:
    header = source.read(HEADER)
    if len(header) != HEADER or not header.startswith(MAGIC):
        raise CoffreError("ce fichier n'est pas une sauvegarde CoGes (en-tête)")
    ephemeral = header[len(MAGIC) : len(MAGIC) + 32]
    salt = header[len(MAGIC) + 32 : len(MAGIC) + 48]
    (chunk,) = struct.unpack(">I", header[-4:])
    if not 1 <= chunk <= 64 * 1024 * 1024:
        raise CoffreError("ce fichier n'est pas une sauvegarde CoGes (taille de bloc)")
    return header, ephemeral, salt, chunk


def _decrypt_with(
    source: BinaryIO, target: BinaryIO | None, header: bytes, key: bytes, chunk: int
) -> str:
    """Déchiffre bloc par bloc ; rend le sha256 du clair. Refuse tout écart."""
    aead = AESGCM(key)
    digest = hashlib.sha256()
    index = 0
    current = source.read(chunk + TAG)
    while True:
        following = source.read(chunk + TAG) if len(current) == chunk + TAG else b""
        last = not following
        if len(current) < TAG:
            raise CoffreError("sauvegarde coupée ou abîmée : la fin manque")
        try:
            block = aead.decrypt(_nonce(index, last), current, header)
        except InvalidTag as error:
            if index == 0:
                raise CoffreError(
                    "mauvaise clé privée, ou sauvegarde abîmée ou modifiée"
                ) from error
            if last:
                raise CoffreError(
                    "sauvegarde coupée, abîmée ou modifiée (fin non authentifiée)"
                ) from error
            raise CoffreError("sauvegarde abîmée ou modifiée") from error
        digest.update(block)
        if target is not None:
            target.write(block)
        if last:
            return digest.hexdigest()
        current = following
        index += 1


def decrypt(source: BinaryIO, target: BinaryIO | None, private: X25519PrivateKey) -> str:
    header, ephemeral, salt, chunk = _read_header(source)
    recipient_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    try:
        shared = private.exchange(X25519PublicKey.from_public_bytes(ephemeral))
    except ValueError as error:
        raise CoffreError("sauvegarde abîmée (clé éphémère)") from error
    return _decrypt_with(
        source, target, header, _derive(shared, salt, ephemeral, recipient_raw), chunk
    )


def check_structure(source: BinaryIO, size: int) -> None:
    """Sans la clé : en-tête lisible et longueur compatible avec des blocs entiers."""
    _header, _ephemeral, _salt, chunk = _read_header(source)
    body = size - HEADER
    full, rest = divmod(body, chunk + TAG)
    if body < TAG or (rest != 0 and rest < TAG) or (rest == 0 and full == 0):
        raise CoffreError("sauvegarde coupée (longueur)")


# ---------------------------------------------------------------------------- commandes


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def cmd_pair(private_path: Path, public_path: Path) -> None:
    key = X25519PrivateKey.generate()
    # « x » : jamais d'écrasement d'une clé existante.
    with private_path.open("x", encoding="ascii") as handle:
        handle.write(encode_private(key) + "\n")
    private_path.chmod(0o600)
    with public_path.open("x", encoding="ascii") as handle:
        handle.write(encode_public(key.public_key()) + "\n")
    print(
        f"Paire tirée : {private_path.name} (PRIVÉE, à ranger chez CoGes) "
        f"et {public_path.name} (publique)."
    )


def cmd_encrypt(public_text: str, source: Path, target: Path) -> None:
    recipient = read_public(public_text)
    partial = target.with_name(target.name + ".partiel")
    with source.open("rb") as plain, partial.open("xb") as sealed:
        key = encrypt(plain, sealed, recipient)
        sealed.flush()
        os.fsync(sealed.fileno())
    # Relecture : le fichier écrit se déchiffre (même clé de contenu) en le même clair.
    with partial.open("rb") as sealed:
        header, _ephemeral, _salt, chunk = _read_header(sealed)
        reread = _decrypt_with(sealed, None, header, key, chunk)
    if reread != _sha256_file(source):
        partial.unlink()
        raise CoffreError("la relecture du fichier chiffré ne redonne pas la sauvegarde")
    partial.rename(target)
    print(f"chiffre {target.stat().st_size} {_sha256_file(target)} {reread}")


def cmd_decrypt(private_text: str, source: Path, target: Path) -> None:
    private = read_private(private_text)
    partial = target.with_name(target.name + ".partiel")
    try:
        with source.open("rb") as sealed, partial.open("wb") as plain:
            digest = decrypt(sealed, plain, private)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.rename(target)
    print(f"dechiffre {target.stat().st_size} {digest}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    pair = sub.add_parser("paire")
    pair.add_argument("--prive", type=Path, required=True)
    pair.add_argument("--publique", type=Path, required=True)
    sub.add_parser("publique")
    enc = sub.add_parser("chiffrer")
    enc.add_argument("--publique", required=True, help="le texte COGES-CLE-PUBLIQUE-1:…")
    enc.add_argument("entree", type=Path)
    enc.add_argument("sortie", type=Path)
    dec = sub.add_parser("dechiffrer")
    dec.add_argument("entree", type=Path)
    dec.add_argument("sortie", type=Path)
    chk = sub.add_parser("controler")
    chk.add_argument("entree", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "paire":
            cmd_pair(args.prive, args.publique)
        elif args.command == "publique":
            print(encode_public(read_private(sys.stdin.read()).public_key()))
        elif args.command == "chiffrer":
            cmd_encrypt(args.publique, args.entree, args.sortie)
        elif args.command == "dechiffrer":
            cmd_decrypt(sys.stdin.read(), args.entree, args.sortie)
        else:
            with args.entree.open("rb") as handle:
                check_structure(handle, args.entree.stat().st_size)
            print("structure conforme")
    except CoffreError as error:
        print(f"ÉCHEC — {error}", file=sys.stderr)
        return 1
    except FileExistsError as error:
        print(
            f"ÉCHEC — le fichier existe déjà, rien n'est écrasé : {error.filename}", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
