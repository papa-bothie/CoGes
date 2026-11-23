"""Palette des pièces PDF (ADR 0112 amendé, ADR 0113).

Une seule palette côté serveur, `app.core.pdf.PALETTE`, égale aux jetons du bloc clair de
`frontend/app/globals.css` (le papier est toujours clair) ; aucune couleur écrite ailleurs
dans les modules qui mettent en page un PDF ; facture claire (lot A, ADR 0130).
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


def test_the_invoice_colours_are_three_tokens() -> None:
    """Facture claire (lot A, ADR 0130) : un seul petit jeu de jetons, accent, accent clair
    et filet, pour qu'une couleur choisie par la boutique remplace un jour l'accent."""
    invoice = {name for name in pdf.PALETTE if name.startswith("coges-facture-")}
    assert invoice == {
        "coges-facture-accent",
        "coges-facture-accent-clair",
        "coges-facture-filet",
    }
    # Plus aucun vert foncé en aplat : les anciens verts ne sont plus dans la palette.
    for gone in ("coges-vert-marque", "coges-vert-action", "coges-sur-action"):
        assert gone not in pdf.PALETTE, gone


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


def test_invoice_text_is_aa_on_every_invoice_surface() -> None:
    """Encre, gris et accent sur le papier, l'accent clair et les lignes alternées : 4,5:1
    au moins ; chaque surface reste claire (luminance 0,80 au moins)."""
    surfaces = ("coges-recu-papier", "coges-facture-accent-clair", "coges-recu-entete")
    for surface in surfaces:
        assert _luminance(pdf.PALETTE[surface]) >= 0.80, surface
        for ink in ("coges-recu-encre", "coges-recu-gris", "coges-facture-accent"):
            assert _contrast(pdf.PALETTE[ink], pdf.PALETTE[surface]) >= 4.5, (ink, surface)


def test_the_invoice_rule_is_visible_against_the_paper() -> None:
    """Le filet borne l'en-tête et le total, même imprimé en gris (3:1, WCAG 1.4.11)."""
    rule = pdf.PALETTE["coges-facture-filet"]
    for surface in ("coges-recu-papier", "coges-facture-accent-clair"):
        assert _contrast(rule, pdf.PALETTE[surface]) >= 3, surface
