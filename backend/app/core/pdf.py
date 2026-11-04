"""Moteur PDF commun des pièces et des exports (ADR 0111, Q0 ; ADR 0113).

ReportLab côté serveur : le même rendu partout, y compris sur un téléphone qui n'imprime
pas. Ce module ne connaît **aucune** règle métier : polices, palette, styles, logo,
pagination « Page n/N » et assemblage d'une page A4 ou d'une bande de ticket. Chaque
module met en page ses propres données avec ces briques.

Polices embarquées : Figtree et JetBrains Mono (OFL), instances statiques Regular et Bold
tirées des fichiers du front (`frontend/app/fonts/`). Elles couvrent les accents, « € »,
« œ » et les guillemets ; l'espace fine insécable (U+202F) n'y est pas et devient une
espace insécable pleine, comme le fait déjà `formatAmount` à l'écran.
"""

from __future__ import annotations

import io
import re
import unicodedata
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, Image, Paragraph, SimpleDocTemplate

FONTS_DIR = Path(__file__).with_name("fonts")

SANS = "Figtree"
SANS_BOLD = "Figtree-Bold"
MONO = "JetBrainsMono"
MONO_BOLD = "JetBrainsMono-Bold"

# Palette d'impression : les jetons `recu-*` du front (DESIGN.md, ADR 0112), lisibles en
# noir et blanc. Aucune couleur de rubrique sur une pièce imprimée.
INK = HexColor("#111111")
GREY = HexColor("#444444")
RULE = HexColor("#e5e5e5")
HEAD_FILL = HexColor("#f5f5f5")

A4_MARGIN = 14 * mm
#: ReportLab attend les constantes `TA_*` (0, 1, 2) ; une chaîne casse le dessin.
_ALIGN: dict[str, Literal[0, 1, 2]] = {"left": 0, "center": 1, "right": 2}
TICKET_WIDTH = 80 * mm
TICKET_MARGIN = 4 * mm
#: Marge intérieure des cadres de `SimpleDocTemplate`, de chaque côté (ReportLab).
FRAME_PADDING = 6
#: Largeur utile d'une page : ce qu'un tableau peut occuper sans déborder.
A4_CONTENT_WIDTH = A4[0] - 2 * A4_MARGIN - 2 * FRAME_PADDING
TICKET_CONTENT_WIDTH = TICKET_WIDTH - 2 * TICKET_MARGIN - 2 * FRAME_PADDING


@cache
def register_fonts() -> None:
    """Enregistre les quatre polices, une fois par processus."""
    for name, file in (
        (SANS, "Figtree-Regular.ttf"),
        (SANS_BOLD, "Figtree-Bold.ttf"),
        (MONO, "JetBrainsMono-Regular.ttf"),
        (MONO_BOLD, "JetBrainsMono-Bold.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, str(FONTS_DIR / file)))
    pdfmetrics.registerFontFamily(SANS, normal=SANS, bold=SANS_BOLD)
    pdfmetrics.registerFontFamily(MONO, normal=MONO, bold=MONO_BOLD)


def text(value: str | None) -> str:
    """Texte saisi par un utilisateur, sûr dans un `Paragraph` (balises échappées)."""
    if not value:
        return ""
    cleaned = value.replace(" ", " ")
    return escape(cleaned).replace("\n", "<br/>")


def style(
    name: str,
    *,
    size: float = 10,
    bold: bool = False,
    mono: bool = False,
    color: Color = INK,
    align: Literal["left", "center", "right"] = "left",
    leading: float | None = None,
    space_after: float = 0,
) -> ParagraphStyle:
    """Un style de paragraphe de la palette d'impression."""
    register_fonts()
    family = (MONO_BOLD if bold else MONO) if mono else (SANS_BOLD if bold else SANS)
    return ParagraphStyle(
        name,
        fontName=family,
        fontSize=size,
        leading=leading or size * 1.3,
        textColor=color,
        alignment=_ALIGN[align],
        spaceAfter=space_after,
    )


def para(value: str, paragraph_style: ParagraphStyle) -> Paragraph:
    """Paragraphe d'un texte **déjà échappé** (`text`) ou composé par le code."""
    return Paragraph(value, paragraph_style)


def logo(
    png: bytes | None, *, max_width: float, max_height: float, grayscale: bool = False
) -> Image | None:
    """Le logo, réduit à la boîte donnée sans déformation ; `None` sans logo.

    `grayscale` pour le ticket (imprimante thermique), comme le filtre de l'écran.
    """
    if not png:
        return None
    with PILImage.open(io.BytesIO(png)) as source:
        if grayscale:
            converted = source.convert("LA" if "A" in source.getbands() else "L")
            buffer = io.BytesIO()
            converted.save(buffer, format="PNG")
            png = buffer.getvalue()
        width, height = source.size
    ratio = min(max_width / width, max_height / height)
    return Image(io.BytesIO(png), width=width * ratio, height=height * ratio)


class _NumberedCanvas(canvas.Canvas):
    """Deux passes : chaque page connaît le total, pour « Page n/N » en bas à droite."""

    footer_left: str = ""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802 — nom imposé par ReportLab
        self._pages.append(dict(self.__dict__))
        self._startPage()  # type: ignore[attr-defined]  # API interne de ReportLab, stable

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._footer(total)
            super().showPage()
        super().save()

    def _footer(self, total: int) -> None:
        width = float(self._pagesize[0])  # type: ignore[attr-defined]
        self.setFont(SANS, 8)
        self.setFillColor(GREY)
        self.drawRightString(width - A4_MARGIN, 8 * mm, f"Page {self.getPageNumber()}/{total}")
        if self.footer_left:
            self.drawString(A4_MARGIN, 8 * mm, self.footer_left)


def build_a4(
    flowables: Sequence[Flowable], *, title: str, author: str, footer_left: str = ""
) -> bytes:
    """Document A4 paginé, « Page n/N » en bas à droite, mention facultative à gauche."""
    register_fonts()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=A4_MARGIN,
        rightMargin=A4_MARGIN,
        topMargin=A4_MARGIN,
        bottomMargin=A4_MARGIN + 4 * mm,
        title=title,
        author=author,
        creator="CoGes",
    )

    class Numbered(_NumberedCanvas):
        pass

    Numbered.footer_left = footer_left
    document.build(list(flowables), canvasmaker=Numbered)
    return buffer.getvalue()


def build_band(flowables: Sequence[Flowable], *, title: str, author: str) -> bytes:
    """Ticket de caisse : 80 mm de large, une seule page aussi haute que son contenu."""
    register_fonts()
    height = 2 * TICKET_MARGIN + 2 * FRAME_PADDING + 4 * mm  # marge de sûreté
    for flowable in flowables:
        _, needed = flowable.wrap(TICKET_CONTENT_WIDTH, 10_000 * mm)
        height += needed + flowable.getSpaceBefore() + flowable.getSpaceAfter()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=(TICKET_WIDTH, height),
        leftMargin=TICKET_MARGIN,
        rightMargin=TICKET_MARGIN,
        topMargin=TICKET_MARGIN,
        bottomMargin=TICKET_MARGIN,
        title=title,
        author=author,
        creator="CoGes",
    )
    document.build(list(flowables))
    return buffer.getvalue()


def attachment(filename: str) -> str:
    """En-tête `Content-Disposition` : nom ASCII, et le même en UTF-8 (RFC 6266)."""
    ascii_name = filename.encode("ascii", "ignore").decode() or "document.pdf"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def slug(value: str) -> str:
    """« Boutique Keur Fatou » → « Boutique-Keur-Fatou » (nom de fichier sans accent)."""
    plain = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", plain).strip("-")[:60] or "CoGes"
