"""Palette des pièces PDF (ADR 0112 amendé, ADR 0113).

Une seule palette côté serveur, `app.core.pdf.PALETTE`, égale aux jetons du bloc clair de
`frontend/app/globals.css` (le papier est toujours clair) ; aucune couleur écrite ailleurs
dans les modules qui mettent en page un PDF ; texte blanc lisible sur les verts.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core import pdf

BACKEND = Path(__file__).resolve().parents[2]
GLOBALS_CSS = BACKEND.parent / "frontend" / "app" / "globals.css"
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")


def _light_tokens() -> dict[str, str]:
    css = GLOBALS_CSS.read_text(encoding="utf-8")
    start = css.index(":root,\n.papier {")
    block = css[start : css.index("\n}", start)]
    return {
        name: value.lower()
        for name, value in re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block)
    }


def test_the_pdf_palette_is_the_light_tokens_of_globals_css() -> None:
    tokens = _light_tokens()
    for name, value in pdf.PALETTE.items():
        assert tokens.get(name) == value.lower(), (name, value, tokens.get(name))


def test_the_invoice_greens_are_in_the_palette() -> None:
    for name in (
        "coges-vert-marque",
        "coges-vert-action",
        "coges-ventes-teinte",
        "coges-sur-action",
    ):
        assert name in pdf.PALETTE


def test_no_colour_is_written_outside_the_palette() -> None:
    engine = (BACKEND / "app" / "core" / "pdf.py").read_text(encoding="utf-8")
    found = HEX.findall(engine)
    assert sorted(found) == sorted(pdf.PALETTE.values()), "une couleur hors de PALETTE"
    for layout in sorted((BACKEND / "app" / "modules").glob("*/documents.py")):
        assert HEX.findall(layout.read_text(encoding="utf-8")) == [], layout.name


def _luminance(hex_value: str) -> float:
    def channel(byte: int) -> float:
        c = byte / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_value[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_white_on_the_greens_is_aa() -> None:
    white = pdf.PALETTE["coges-sur-action"]
    assert _contrast(white, pdf.PALETTE["coges-vert-marque"]) >= 7
    assert _contrast(white, pdf.PALETTE["coges-vert-action"]) >= 4.5
