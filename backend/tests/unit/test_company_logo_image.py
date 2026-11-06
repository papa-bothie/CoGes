"""Traitement du logo de l'entreprise (prompt 35, bloc L, ADR 0111).

Le serveur lit le vrai type dans le contenu, jamais dans le nom ; il ré-encode l'image en
PNG (ce qui retire toute métadonnée, dont la position GPS d'une photo), la réduit à 512 px
de côté au plus, et refuse le reste avec un message clair.
"""

from __future__ import annotations

import hashlib
import io
import struct
import zlib

import pytest
from PIL import Image

from app.modules.companies.logo import (
    MAX_LOGO_UPLOAD_BYTES,
    MAX_SIDE,
    PNG_BUDGET_BYTES,
    LogoTooLargeError,
    LogoUnsupportedFormatError,
    normalize_logo,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _image(fmt: str, size: tuple[int, int] = (64, 32), **save: object) -> bytes:
    mode = "RGBA" if fmt == "PNG" else "RGB"
    image = Image.new(mode, size, (200, 30, 30, 255) if mode == "RGBA" else (200, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save)
    return buffer.getvalue()


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_png_jpeg_and_webp_become_a_png(fmt: str) -> None:
    logo = normalize_logo(_image(fmt))
    assert logo.png.startswith(PNG_SIGNATURE)
    assert (logo.width, logo.height) == (64, 32)
    assert logo.sha256 == hashlib.sha256(logo.png).hexdigest()
    assert logo.byte_size == len(logo.png)


def test_the_type_is_read_in_the_content_not_the_name() -> None:
    """Le nom n'est même pas lu : un JPEG reste un JPEG, un texte reste refusé."""
    assert normalize_logo(_image("JPEG")).png.startswith(PNG_SIGNATURE)
    with pytest.raises(LogoUnsupportedFormatError):
        normalize_logo(b"Ceci n'est pas une image, malgre le nom logo.png")


def test_svg_is_refused() -> None:
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        b"<script>alert(1)</script></svg>"
    )
    with pytest.raises(LogoUnsupportedFormatError) as refused:
        normalize_logo(svg)
    assert refused.value.code == "logo_unsupported_format"
    assert refused.value.message == "Format non pris en charge : PNG, JPEG ou WebP."


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF"])
def test_other_image_formats_are_refused(fmt: str) -> None:
    with pytest.raises(LogoUnsupportedFormatError):
        normalize_logo(_image(fmt))


def test_a_truncated_image_is_refused() -> None:
    with pytest.raises(LogoUnsupportedFormatError):
        normalize_logo(_image("PNG", (300, 300))[:200])


def test_a_photo_loses_its_gps_position_and_every_metadata() -> None:
    exif = Image.Exif()
    exif[0x010F] = "Appareil"  # Make
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (14.0, 41.0, 30.0)  # Dakar
    photo = _image("JPEG", (80, 60), exif=exif.tobytes())
    assert b"Appareil" in photo, "la photo de départ porte bien ses métadonnées"

    logo = normalize_logo(photo)
    assert b"Appareil" not in logo.png
    with Image.open(io.BytesIO(logo.png)) as reread:
        assert not reread.getexif(), "aucune donnée EXIF ne survit"
        assert set(reread.info) <= {"dpi", "gamma"}, reread.info


def test_the_exif_orientation_is_applied_before_it_is_dropped() -> None:
    """Une photo de téléphone tenue debout reste debout une fois les métadonnées ôtées."""
    exif = Image.Exif()
    exif[0x0112] = 6  # pivotée de 90°
    logo = normalize_logo(_image("JPEG", (80, 40), exif=exif.tobytes()))
    assert (logo.width, logo.height) == (40, 80)


def test_a_large_image_is_reduced_to_512_px_on_its_longest_side() -> None:
    logo = normalize_logo(_image("PNG", (2000, 1000)))
    assert (logo.width, logo.height) == (MAX_SIDE, 256)
    assert MAX_SIDE == 512


def test_a_flat_logo_weighs_a_few_dozen_ko() -> None:
    flat = Image.new("RGB", (900, 900), (255, 255, 255))
    flat.paste((20, 90, 50), (100, 100, 800, 500))
    buffer = io.BytesIO()
    flat.save(buffer, format="JPEG", quality=90)
    assert normalize_logo(buffer.getvalue()).byte_size < 50_000


def test_the_stored_png_stays_small() -> None:
    """Une photo bruitée de 4000 px devient un PNG de quelques dizaines de Ko."""
    noisy = Image.effect_noise((1600, 1600), 60).convert("RGB")
    buffer = io.BytesIO()
    noisy.save(buffer, format="JPEG", quality=70)
    assert len(buffer.getvalue()) <= MAX_LOGO_UPLOAD_BYTES
    logo = normalize_logo(buffer.getvalue())
    assert logo.byte_size <= PNG_BUDGET_BYTES, logo.byte_size


def test_more_than_2_mo_is_refused_before_decoding() -> None:
    assert MAX_LOGO_UPLOAD_BYTES == 2 * 1024 * 1024
    with pytest.raises(LogoTooLargeError) as refused:
        normalize_logo(b"\x89PNG" + b"\x00" * MAX_LOGO_UPLOAD_BYTES)
    assert refused.value.status_code == 413
    assert refused.value.code == "logo_too_large"
    assert refused.value.message == "Image trop lourde (2 Mo au plus)."


def test_a_decompression_bomb_is_refused() -> None:
    """Quelques Ko annoncent 20 000 × 20 000 pixels : refusé sans décoder."""
    bomb = PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", 20_000, 20_000, 8, 6, 0, 0, 0))
    bomb += _chunk(b"IDAT", zlib.compress(b"\x00" * 1024)) + _chunk(b"IEND", b"")
    with pytest.raises(LogoUnsupportedFormatError):
        normalize_logo(bomb)


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(LogoUnsupportedFormatError):
        normalize_logo(b"")
