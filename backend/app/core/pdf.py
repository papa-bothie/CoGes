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

#: **Seule** palette des PDF : les jetons du bloc clair de `frontend/app/globals.css`,
#: valeur pour valeur (`tests/unit/test_pdf_palette.py` le vérifie ; aucune couleur n'est
#: écrite ailleurs). Le papier est toujours clair. Le ticket et les exports n'emploient que
#: les `recu-*` (noir et blanc) ; la facture A4 prend aussi les verts (ADR 0112 amendé).
PALETTE: dict[str, str] = {
    "coges-recu-papier": "#ffffff",
    "coges-recu-encre": "#111111",
    "coges-recu-gris": "#444444",
    "coges-recu-filet": "#e5e5e5",
    "coges-recu-entete": "#f5f5f5",
    "coges-vert-marque": "#024a2c",
    "coges-vert-action": "#117a3c",
    "coges-ventes-teinte": "#e6f4ec",
    "coges-sur-action": "#ffffff",
}


def color(token: str) -> Color:
    """La couleur d'un jeton de la palette."""
    return HexColor(PALETTE[token])


PAPER = color("coges-recu-papier")
INK = color("coges-recu-encre")
GREY = color("coges-recu-gris")
RULE = color("coges-recu-filet")
HEAD_FILL = color("coges-recu-entete")
#: Titre, bandeaux du tableau et du total de la facture ; texte `ON_GREEN` dessus (11:1).
BRAND = color("coges-vert-marque")
#: Filet de l'en-tête, pastilles et intitulés de la facture (5,4:1 sous le blanc).
ACTION = color("coges-vert-action")
#: Fond léger du cadre « Facturé à ».
TINT = color("coges-ventes-teinte")
ON_GREEN = color("coges-sur-action")

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


class Pastille(Flowable):
    """Pastille ronde verte à icône blanche, devant une coordonnée de l'en-tête de la
    facture : `phone` (combiné) ou `pin` (repère d'adresse), dessinés au trait."""

    def __init__(self, icon: Literal["phone", "pin"], size: float = 5.5 * mm) -> None:
        super().__init__()
        self.icon = icon
        self.size = size

    def wrap(self, *_: float) -> tuple[float, float]:
        return self.size, self.size

    def draw(self) -> None:
        c = self.canv
        r = self.size / 2
        c.setFillColor(ACTION)
        c.circle(r, r, r, stroke=0, fill=1)
        c.setStrokeColor(ON_GREEN)
        c.setFillColor(ON_GREEN)
        c.setLineWidth(0.9)
        if self.icon == "phone":
            # Un téléphone : boîtier arrondi et sa touche.
            c.roundRect(r - 0.32 * r, r - 0.5 * r, 0.64 * r, r, 0.12 * r, stroke=1, fill=0)
            c.circle(r, r - 0.32 * r, 0.06 * r, stroke=0, fill=1)
        else:
            # Un repère : cercle et pointe.
            c.circle(r, r + 0.12 * r, 0.3 * r, stroke=1, fill=0)
            c.line(r - 0.22 * r, r - 0.08 * r, r, r - 0.55 * r)
            c.line(r + 0.22 * r, r - 0.08 * r, r, r - 0.55 * r)


class Initials(Flowable):
    """Initiales de la boutique dans un rond `vert-marque`, quand il n'y a pas de logo.

    Dessinées par `drawCentredString` : jamais lues comme balise."""

    def __init__(self, letters: str, size: float = 15 * mm) -> None:
        super().__init__()
        self.letters = letters
        self.size = size

    def wrap(self, *_: float) -> tuple[float, float]:
        return self.size, self.size

    def draw(self) -> None:
        c = self.canv
        r = self.size / 2
        c.setFillColor(BRAND)
        c.circle(r, r, r, stroke=0, fill=1)
        c.setFillColor(ON_GREEN)
        font = 0.42 * self.size
        c.setFont(SANS_BOLD, font)
        c.drawCentredString(r, r - 0.36 * font, self.letters)


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


#: Ce qui casserait l'en-tête ou tromperait le navigateur : guillemet, barre oblique
#: inverse et caractères de contrôle (retour à la ligne compris).
_UNSAFE_IN_FILENAME = re.compile(r'["\\\x00-\x1f\x7f]')


def attachment(filename: str) -> str:
    """En-tête `Content-Disposition` : nom ASCII, et le même en UTF-8 (RFC 6266).

    Le nom est nettoyé d'abord : ni guillemet, ni `\\`, ni caractère de contrôle, dans
    aucune des deux formes.
    """
    cleaned = _UNSAFE_IN_FILENAME.sub("", filename).strip()
    plain = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode().strip()
    if not plain.strip(". "):
        plain = "document.pdf"
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(cleaned or plain)}"


def slug(value: str) -> str:
    """« Boutique Keur Fatou » → « Boutique-Keur-Fatou » (nom de fichier sans accent)."""
    plain = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", plain).strip("-")[:60] or "CoGes"
