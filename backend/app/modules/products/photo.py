"""Photo d'un article : vérifiée et ré-encodée avant de partir (ADR 0121). Ni base, ni HTTP.

Même règle que le logo (ADR 0111) : le type est lu dans le **contenu**, jamais dans le
nom ni dans le type annoncé ; seuls PNG, JPEG et WebP passent (SVG refusé : il porte du
script) ; l'image est **ré-encodée**, ce qui retire toute métadonnée (position GPS d'une
photo de téléphone, appareil, date) ; une « bombe de décompression » est refusée sans
être décodée. En JPEG, et non en PNG : c'est une photo, pas un aplat.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import CogesError, ValidationFailedError

#: Poids maximal du fichier envoyé, avant tout décodage.
MAX_PHOTO_UPLOAD_BYTES = 5 * 1024 * 1024
#: Plus grand côté gardé, en pixels.
MAX_SIDE = 1600
#: Au-delà, refusée sans décodage. 40 Mpx couvrent toute photo de téléphone.
MAX_SOURCE_PIXELS = 40_000_000
JPEG_QUALITY = 85

_ACCEPTED_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})


class PhotoTooLargeError(CogesError):
    code = "photo_too_large"
    status_code = 413
    default_message = "Image trop lourde (5 Mo au plus)."


class PhotoUnsupportedFormatError(ValidationFailedError):
    code = "photo_unsupported_format"
    default_message = "Format non pris en charge : une photo PNG, JPEG ou WebP."


@dataclass(frozen=True, slots=True)
class NormalizedPhoto:
    jpeg: bytes
    width: int
    height: int


def normalize_photo(content: bytes) -> NormalizedPhoto:
    """Vérifie, ré-encode en JPEG sans métadonnée et réduit à 1600 px de côté."""
    if len(content) > MAX_PHOTO_UPLOAD_BYTES:
        raise PhotoTooLargeError()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content), formats=sorted(_ACCEPTED_FORMATS)) as source:
                width, height = source.size
                if width * height > MAX_SOURCE_PIXELS:
                    raise PhotoUnsupportedFormatError()
                source.seek(0)  # première image d'un PNG ou WebP animé
                source.load()
                # La photo de téléphone tournée par l'EXIF est remise droite, puis l'EXIF
                # disparaît avec le reste.
                image = ImageOps.exif_transpose(source)
    except PhotoUnsupportedFormatError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise PhotoUnsupportedFormatError() from exc

    # La transparence est posée sur du blanc : un JPEG n'en a pas.
    rgba = image.convert("RGBA")
    clean = Image.new("RGB", rgba.size, (255, 255, 255))
    clean.paste(rgba, mask=rgba.getchannel("A"))
    clean.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    clean.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return NormalizedPhoto(jpeg=buffer.getvalue(), width=clean.width, height=clean.height)
