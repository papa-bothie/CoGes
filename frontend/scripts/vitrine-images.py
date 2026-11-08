"""Images de la page d'accueil publique (prompt 37, ADR 0115).

Convertit les captures de `e2e/captures-vitrine.spec.ts` (démo, jamais de données réelles) en
WebP pour `public/vitrine/`, et l'image de partage en PNG compressé (les aperçus de WhatsApp et
des réseaux lisent mal le WebP).

    uv run --directory backend python ../frontend/scripts/vitrine-images.py <dossier des captures>
"""

import sys
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "public" / "vitrine"


def main(source: Path) -> None:
    for name in ("ordinateur", "telephone"):
        with Image.open(source / f"{name}.png") as image:
            target = OUT / f"apercu-{name}.webp"
            image.convert("RGB").save(target, "WEBP", quality=78, method=6)
    with Image.open(source / "partage.png") as image:
        image.convert("RGB").quantize(colors=128, method=Image.Quantize.MEDIANCUT).save(
            OUT / "partage.png", "PNG", optimize=True
        )
    for path in sorted(OUT.iterdir()):
        size = Image.open(path).size if path.suffix != ".svg" else "svg"
        print(f"{path.name}: {path.stat().st_size // 1024} Ko {size}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
