"""Traitement du logo de l'entreprise (ADR 0111). Aucune base, aucun HTTP.

Le type est lu dans le **contenu** (signature reconnue par Pillow), jamais dans le nom
ni dans le type annoncé par le navigateur. Seuls PNG, JPEG et WebP passent : SVG est
refusé (il porte du script), comme tout le reste. L'image est **ré-encodée** en PNG :
ce qui sort ne garde aucune métadonnée de ce qui entre (position GPS d'une photo,
commentaires, profils), et un fichier piégé ne survit pas au décodage.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import CogesError, ValidationFailedError

#: Poids maximal du fichier envoyé, avant tout décodage.
MAX_LOGO_UPLOAD_BYTES = 2 * 1024 * 1024
#: Plus grand côté du logo gardé, en pixels.
MAX_SIDE = 512
#: Au-delà, l'image annonce plus de pixels qu'un logo n'en a besoin : refusée sans être
#: décodée (« bombe de décompression »). 40 Mpx couvrent toute photo de téléphone.
MAX_SOURCE_PIXELS = 40_000_000
#: Poids visé du PNG gardé. Un logo réel (aplats) pèse quelques dizaines de Ko ; une
#: photo bruitée passe en palette de 256 couleurs, puis rétrécit, jusqu'à tenir dessous.
#: La base borne à 256 Ko (révision 0036).
PNG_BUDGET_BYTES = 200_000

_ACCEPTED_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})


class LogoTooLargeError(CogesError):
    code = "logo_too_large"
    status_code = 413
    default_message = "Image trop lourde (2 Mo au plus)."


class LogoUnsupportedFormatError(ValidationFailedError):
    code = "logo_unsupported_format"
    default_message = "Format non pris en charge : PNG, JPEG ou WebP."


@dataclass(frozen=True, slots=True)
class NormalizedLogo:
    png: bytes
    width: int
    height: int
    sha256: str

    @property
    def byte_size(self) -> int:
        return len(self.png)


def normalize_logo(content: bytes) -> NormalizedLogo:
    """Vérifie, ré-encode et réduit le logo ; lève une erreur au message affichable."""
    if len(content) > MAX_LOGO_UPLOAD_BYTES:
        raise LogoTooLargeError()
    try:
        with warnings.catch_warnings():
            # Pillow avertit avant de lever DecompressionBombError : l'avertissement
            # devient une erreur, et la limite propre au logo s'applique d'abord.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content), formats=sorted(_ACCEPTED_FORMATS)) as source:
                width, height = source.size
                if width * height > MAX_SOURCE_PIXELS:
                    raise LogoUnsupportedFormatError()
                source.seek(0)  # première image d'un PNG ou WebP animé
                source.load()
                image = ImageOps.exif_transpose(source)
    except LogoUnsupportedFormatError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise LogoUnsupportedFormatError() from exc

    # Une copie « propre » : seuls les pixels passent, `info` (EXIF, ICC, texte) reste.
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )
    pixels = image.convert("RGBA" if has_alpha else "RGB")
    clean = Image.new(pixels.mode, pixels.size)
    clean.paste(pixels)
    clean.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)

    png = _encode(clean)
    if len(png) > PNG_BUDGET_BYTES:
        clean = clean.quantize(256)
        png = _encode(clean)
    while len(png) > PNG_BUDGET_BYTES:
        side = max(1, int(max(clean.size) * 0.75))
        clean.thumbnail((side, side), Image.Resampling.LANCZOS)
        png = _encode(clean)
    return NormalizedLogo(
        png=png, width=clean.width, height=clean.height, sha256=hashlib.sha256(png).hexdigest()
    )


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
