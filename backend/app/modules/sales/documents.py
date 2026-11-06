"""Ticket, facture et bon de retour en PDF (prompt 35, bloc T, ADR 0113).

Fonctions **pures** : la lecture du reçu (`build_receipt`, la même que l'écran et
l'impression, ADR 0112) entre, des octets sortent. Même mise en page que l'impression du
navigateur : facture A4 à tableau, ticket 80 mm en chasse fixe, bon de retour au gabarit du
ticket. Aucune requête ici ; le service assemble les données.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    KeepTogether,
    Spacer,
    Table,
    TableStyle,
)

from app.core import pdf
from app.core.display import PAYMENT_METHODS, amount, amount_in_words, figure, qty, qty_with_unit
from app.modules.sales.schemas import ReceiptCompany, ReceiptRead, SaleReturnDetail

MONTHS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


@dataclass(frozen=True, slots=True)
class SlipLine:
    """Ligne d'un bon de retour : ce qui est revenu, au prix de la vente."""

    name: str
    qty: Decimal
    unit_price: Decimal
    refund_amount: Decimal


def document_number(document_no: str) -> str:
    """« V-001044 » → « 1044 », « R-000007 » → « 0007 » : quatre chiffres au moins."""
    digits = document_no.rsplit("-", 1)[-1]
    return f"{int(digits):04d}" if digits.isdigit() else pdf.slug(document_no)


def filename(kind: str, document_no: str, shop: str) -> str:
    """« Facture-1044-Boutique-Keur-Fatou.pdf »."""
    return f"{kind}-{document_number(document_no)}-{pdf.slug(shop)}.pdf"


def _short_no(document_no: str) -> str:
    digits = document_no.rsplit("-", 1)[-1]
    return str(int(digits)) if digits.isdigit() else document_no


def _local(moment: datetime, tz: str) -> datetime:
    return moment.astimezone(ZoneInfo(tz))


def _date_time(moment: datetime, tz: str) -> str:
    return _local(moment, tz).strftime("%d/%m/%Y %H:%M")


def _date_long(moment: datetime, tz: str) -> str:
    local = _local(moment, tz)
    return f"{local.day} {MONTHS[local.month - 1]} {local.year}"


def _paid_by_method(receipt: ReceiptRead) -> list[tuple[str, Decimal]]:
    """Paiements vivants additionnés par moyen, dans l'ordre d'arrivée (comme l'écran)."""
    totals: dict[str, Decimal] = {}
    for payment in receipt.payments:
        if payment.cancelled or payment.reversal_of_payment_id:
            continue
        totals[payment.method] = totals.get(payment.method, Decimal(0)) + payment.amount
    return [(PAYMENT_METHODS.get(method, method), total) for method, total in totals.items()]


def _ids(receipt: ReceiptRead) -> str:
    company = receipt.company
    return " · ".join(
        part
        for part in (company.ninea and f"NINEA {company.ninea}", company.rc and f"RC {company.rc}")
        if part
    )


def _initials(name: str) -> str:
    """Premières lettres des deux derniers mots, signes ignorés : « Diop & Fils <Keur> »
    → « FK ». Le résultat passe encore par `pdf.text` avant ReportLab."""
    letters = [
        next(c for c in word if c.isalnum())
        for word in name.split()
        if any(c.isalnum() for c in word)
    ]
    return "".join(letters[-2:]).upper()


def _seller(receipt: ReceiptRead) -> str:
    """Nom du vendeur sans espaces autour ; vide s'il n'y en a pas."""
    return (receipt.seller_name or "").strip()


def _line_no(index: int) -> str:
    """« 01 », « 02 »… : le numéro d'une ligne de la facture."""
    return f"{index + 1:02d}"


# --------------------------------------------------------------------- facture A4


def render_invoice(receipt: ReceiptRead, *, logo_png: bytes | None, tz: str) -> bytes:
    """Facture A4 au vert CoGes, même mise en page que l'écran (ADR 0112 amendé) : en-tête
    à logo et pastilles, filet vert ; « De » et titre ; « Facturé à » ; tableau à bandeau
    répété sur chaque page et lignes alternées ; totaux à bandeau ; bas de page avec les
    moyens de paiement et le cadre de signature. Couleurs : `pdf.PALETTE` seulement."""
    company = receipt.company
    cur = company.currency
    sold = receipt.confirmed_at or receipt.sold_at
    cancelled = receipt.status == "cancelled"
    width = pdf.A4_CONTENT_WIDTH
    grey_hex = pdf.PALETTE["coges-recu-gris"]
    base = pdf.style("base", size=10)
    grey = pdf.style("grey", size=9, color=pdf.GREY)
    bold = pdf.style("bold", size=10, bold=True)
    right = pdf.style("right", size=10, align="right")
    right_bold = pdf.style("right-bold", size=10, bold=True, align="right")
    label = pdf.style("label", size=8, bold=True, color=pdf.ACTION)
    band = pdf.style("band", size=8, bold=True, color=pdf.ON_GREEN)
    band_right = pdf.style("band-right", size=8, bold=True, color=pdf.ON_GREEN, align="right")
    flat = [
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]

    # En-tête : logo (ou initiales) et nom à gauche, coordonnées à pastilles à droite.
    image = pdf.logo(logo_png, max_width=34 * mm, max_height=16 * mm)
    mark: Flowable = image or pdf.Initials(_initials(company.name))
    name = pdf.para(pdf.text(company.name), pdf.style("shop", size=14, bold=True, color=pdf.BRAND))
    brand = Table(
        [[mark, name]],
        colWidths=[(image.drawWidth if image else 15 * mm) + 4 * mm, None],
        style=TableStyle(flat),
        hAlign="LEFT",
    )
    contacts: list[Flowable] = []
    widths: list[float] = []
    coordinates: list[tuple[Literal["phone", "pin"], str | None, float]] = [
        ("phone", company.phone, 30 * mm),
        ("pin", company.address, 52 * mm),
    ]
    for icon, value, room in coordinates:
        if value:
            contacts += [
                pdf.Pastille(icon),
                pdf.para(pdf.text(value), pdf.style("contact", size=8.5)),
            ]
            widths += [7.5 * mm, room]
    right_room = sum(widths)
    header = Table(
        [[brand, Table([contacts], colWidths=widths, style=TableStyle(flat)) if contacts else ""]],
        colWidths=[width - right_room, right_room],
        style=TableStyle(
            [
                *flat,
                ("LINEBELOW", (0, 0), (-1, 0), 1.5, pdf.ACTION),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
            ]
        ),
    )

    # « De » à gauche, grand titre « FACTURE », numéro, date et vendeur à droite.
    sender: list[Flowable] = [
        pdf.para("DE", label),
        pdf.para(pdf.text(company.name), pdf.style("from", size=12, bold=True)),
    ]
    if company.address:
        sender.append(pdf.para(pdf.text(company.address), base))
    if company.phone:
        sender.append(pdf.para(pdf.text(f"Tél. {company.phone}"), base))
    if ids := _ids(receipt):
        sender.append(pdf.para(pdf.text(ids), grey))
    facts = Table(
        [
            [
                pdf.para("Facture n°", right_bold),
                pdf.para(f"F-{_short_no(receipt.sale_no)}", right),
            ],
            [pdf.para("Date", right_bold), pdf.para(pdf.text(_date_long(sold, tz)), right)],
        ],
        colWidths=[28 * mm, 34 * mm],
        hAlign="RIGHT",
        style=TableStyle([*flat, ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]),
    )
    title: list[Flowable] = [
        pdf.para("FACTURE", pdf.style("title", size=30, bold=True, color=pdf.BRAND, align="right")),
        Spacer(1, 2.5 * mm),
        facts,
    ]
    if seller := _seller(receipt):
        title.append(
            pdf.para(
                pdf.text(f"Servi par : {seller}"),
                pdf.style("seller", size=9, color=pdf.GREY, align="right"),
            )
        )
    parties = Table(
        [[sender, title]],
        colWidths=[width - 70 * mm, 70 * mm],
        style=TableStyle([*flat, ("VALIGN", (0, 0), (-1, -1), "TOP")]),
    )

    # « Facturé à » : le client, ou « Client de passage ».
    billed: list[Flowable] = [
        pdf.para("FACTURÉ À", label),
        pdf.para(
            pdf.text(receipt.customer.name if receipt.customer else "Client de passage"),
            pdf.style("client", size=11, bold=True),
        ),
    ]
    if receipt.customer and receipt.customer.phone:
        billed.append(pdf.para(pdf.text(f"Tél. {receipt.customer.phone}"), base))
    billed_to = Table(
        [[billed]],
        colWidths=[90 * mm],
        hAlign="LEFT",
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), pdf.TINT),
                ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        ),
    )

    story: list[Flowable] = []
    if cancelled:
        story.append(
            pdf.para("VENTE ANNULÉE", pdf.style("cancelled", size=16, bold=True, align="center"))
        )
    story += [header, Spacer(1, 6 * mm), parties, Spacer(1, 4 * mm), billed_to, Spacer(1, 5 * mm)]

    # Tableau : bandeau vert répété, N°, désignation (description et remise en petit).
    rows: list[list[Flowable | str]] = [
        [
            pdf.para("N°", band),
            pdf.para("DÉSIGNATION", band),
            pdf.para("PRIX UNITAIRE", band_right),
            pdf.para("QTÉ", band_right),
            pdf.para("TOTAL", band_right),
        ]
    ]
    for index, line in enumerate(receipt.lines):
        designation = f"<b>{pdf.text(line.name)}</b>"
        for small in (
            line.description,
            f"Remise : -{amount(line.discount, cur)}" if line.discount > 0 else None,
        ):
            if small:
                designation += f'<br/><font size="8" color="{grey_hex}">{pdf.text(small)}</font>'
        rows.append(
            [
                pdf.para(_line_no(index), grey),
                pdf.para(designation, base),
                pdf.para(pdf.text(amount(line.unit_price, cur)), right),
                pdf.para(pdf.text(qty_with_unit(line.qty, line.unit)), right),
                pdf.para(pdf.text(amount(line.line_total, cur)), right),
            ]
        )
    story.append(
        Table(
            rows,
            colWidths=[12 * mm, width - 12 * mm - 3 * 28 * mm, 28 * mm, 28 * mm, 28 * mm],
            repeatRows=1,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), pdf.BRAND),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [pdf.PAPER, pdf.HEAD_FILL]),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.5, pdf.RULE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, 0), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ]
            ),
        )
    )

    # Totaux à droite : détail, bandeau « Total », puis payé et reste (jamais si annulée).
    totals: list[list[Flowable]] = []

    def total_row(text: str, value: str, *, strong: bool = False) -> None:
        totals.append(
            [
                pdf.para(pdf.text(text), bold if strong else base),
                pdf.para(pdf.text(value), right_bold if strong else right),
            ]
        )

    if receipt.discount_total > 0 or receipt.tax_total > 0:
        total_row("Sous-total", amount(receipt.subtotal, cur))
        if receipt.discount_total > 0:
            total_row("Remises", f"-{amount(receipt.discount_total, cur)}")
        if receipt.tax_total > 0:
            total_row("TVA", amount(receipt.tax_total, cur))
    total_index = len(totals)
    totals.append(
        [
            pdf.para("Total", pdf.style("total", size=12, bold=True, color=pdf.ON_GREEN)),
            pdf.para(
                pdf.text(amount(receipt.total, cur)),
                pdf.style("total-right", size=12, bold=True, color=pdf.ON_GREEN, align="right"),
            ),
        ]
    )
    if not cancelled:
        total_row("Déjà payé", amount(receipt.paid_total, cur))
        if receipt.balance > 0:
            total_row("Reste à payer", amount(receipt.balance, cur), strong=True)
    story += [
        Spacer(1, 4 * mm),
        Table(
            totals,
            colWidths=[50 * mm, 35 * mm],
            hAlign="RIGHT",
            style=TableStyle(
                [
                    ("BACKGROUND", (0, total_index), (-1, total_index), pdf.BRAND),
                    ("TOPPADDING", (0, total_index), (-1, total_index), 7),
                    ("BOTTOMPADDING", (0, total_index), (-1, total_index), 7),
                ]
            ),
        ),
    ]

    if receipt.returns:
        returned: list[Flowable] = [pdf.para("RETOURS SUR CETTE VENTE", label)]
        for item in receipt.returns:
            text = f"Retour n° {_short_no(item.return_no)} du {_date_long(item.returned_at, tz)}"
            returned.append(
                Table(
                    [
                        [
                            pdf.para(pdf.text(text), base),
                            pdf.para(pdf.text(f"-{amount(item.total_refund, cur)}"), right),
                        ]
                    ],
                    colWidths=[width - 35 * mm, 35 * mm],
                )
            )
        story += [Spacer(1, 5 * mm), KeepTogether(returned)]

    vat = (
        f"Dont TVA : {amount(receipt.tax_total, cur)}."
        if receipt.tax_total > 0
        else "TVA non applicable."
    )
    # Une vente annulée ne réclame rien : ni reste à payer, ni somme arrêtée.
    story.append(Spacer(1, 5 * mm))
    if not cancelled:
        story.append(
            pdf.para(
                "Arrêtée la présente facture à la somme de : "
                f"<b>{pdf.text(amount_in_words(receipt.total))}</b>.",
                base,
            )
        )
    story += [pdf.para(pdf.text(vat), grey), Spacer(1, 6 * mm)]

    # Bas de page : merci, moyens de paiement, pied de reçu ; cadre de signature à droite.
    thanks: list[Flowable] = [
        pdf.para("Merci pour votre confiance", pdf.style("thanks", size=12, bold=True)),
    ]
    methods = _paid_by_method(receipt)
    if methods:
        thanks += [Spacer(1, 2.5 * mm), pdf.para("MOYENS DE PAIEMENT", label)]
        thanks += [
            pdf.para(pdf.text(f"{method} : {amount(paid, cur)}"), base) for method, paid in methods
        ]
    if company.receipt_footer:
        thanks += [Spacer(1, 2.5 * mm), pdf.para(pdf.text(company.receipt_footer), grey)]
    thanks += [
        Spacer(1, 2 * mm),
        pdf.para("Facture éditée avec CoGes", pdf.style("small", size=7.5, color=pdf.GREY)),
    ]
    signature = Table(
        [
            [
                pdf.para(
                    "Signature et cachet", pdf.style("sign", size=9, color=pdf.GREY, align="center")
                )
            ]
        ],
        colWidths=[58 * mm],
        rowHeights=[24 * mm],
        style=TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1.5, pdf.RULE),
                ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
    )
    story.append(
        KeepTogether(
            [
                Table(
                    [[thanks, signature]],
                    colWidths=[width - 64 * mm, 64 * mm],
                    style=TableStyle(
                        [
                            *flat,
                            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                        ]
                    ),
                )
            ]
        )
    )
    return pdf.build_a4(
        story, title=f"Facture n° {_short_no(receipt.sale_no)}", author=company.name
    )


# --------------------------------------------------------------------- ticket 80 mm


def _dash() -> HRFlowable:
    return HRFlowable(
        width="100%", thickness=0.6, color=pdf.INK, dash=(2, 2), spaceBefore=4, spaceAfter=4
    )


def _row(
    left: str,
    right: str,
    *,
    strong: bool = False,
    indent: bool = False,
    right_width: float = 22 * mm,
) -> Table:
    """Ligne gauche / droite du ticket ; `indent` décale d'un retrait (quantité × prix)."""
    left_style = pdf.style("t-left-b" if strong else "t-left", size=8.5, mono=True, bold=strong)
    if indent:
        left_style.leftIndent = 8
    right_style = pdf.style(
        "t-right-b" if strong else "t-right", size=8.5, mono=True, bold=strong, align="right"
    )
    frame = pdf.TICKET_CONTENT_WIDTH
    return Table(
        [[pdf.para(pdf.text(left), left_style), pdf.para(pdf.text(right), right_style)]],
        colWidths=[frame - right_width, right_width],
        style=TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        ),
    )


def _ticket_header(receipt_company: ReceiptCompany, logo_png: bytes | None) -> list[Flowable]:
    center = pdf.style("t-center", size=8.5, mono=True, align="center")
    center_bold = pdf.style("t-center-b", size=8.5, mono=True, bold=True, align="center")
    story: list[Flowable] = []
    image = pdf.logo(logo_png, max_width=40 * mm, max_height=16 * mm, grayscale=True)
    if image is not None:
        story += [image, Spacer(1, 2 * mm)]
    story.append(
        pdf.para(
            pdf.text(receipt_company.name.upper()),
            pdf.style("t-shop", size=10, mono=True, bold=True, align="center"),
        )
    )
    if receipt_company.address:
        story.append(pdf.para(pdf.text(receipt_company.address), center_bold))
    if receipt_company.phone:
        story.append(pdf.para(pdf.text(f"Tél. {receipt_company.phone}"), center))
    return story


def render_ticket(receipt: ReceiptRead, *, logo_png: bytes | None, tz: str) -> bytes:
    """Petit ticket 80 mm (ADR 0112) : lignes courtes, mêmes totaux, pied de reçu."""
    cur = receipt.company.currency
    plain = pdf.style("t-plain", size=8.5, mono=True)
    center = pdf.style("t-center", size=8.5, mono=True, align="center")
    story = _ticket_header(receipt.company, logo_png)
    if receipt.status == "cancelled":
        story.append(
            pdf.para(
                "VENTE ANNULÉE",
                pdf.style("t-cancel", size=11, mono=True, bold=True, align="center"),
            )
        )
    story += [
        _dash(),
        _row(
            f"Vente n° {_short_no(receipt.sale_no)}",
            _date_time(receipt.confirmed_at or receipt.sold_at, tz),
            right_width=34 * mm,
        ),
    ]
    if receipt.customer:
        story.append(pdf.para(pdf.text(f"Client : {receipt.customer.name}"), plain))
    if seller := _seller(receipt):
        story.append(pdf.para(pdf.text(f"Servi par : {seller.split()[0]}"), plain))
    story.append(_dash())
    for line in receipt.lines:
        story.append(pdf.para(pdf.text(line.name), plain))
        story.append(
            _row(
                f"{qty(line.qty)} x {figure(line.unit_price)}",
                figure(line.line_total),
                indent=True,
            )
        )
        if line.discount > 0:
            story.append(_row("remise", f"-{figure(line.discount)}", indent=True))
    story.append(_dash())
    if receipt.discount_total > 0 or receipt.tax_total > 0:
        story.append(_row("Sous-total", amount(receipt.subtotal, cur)))
        if receipt.discount_total > 0:
            story.append(_row("Remises", f"-{amount(receipt.discount_total, cur)}"))
        if receipt.tax_total > 0:
            story.append(_row("TVA", amount(receipt.tax_total, cur)))
    story.append(_row("TOTAL", amount(receipt.total, cur), strong=True))
    methods = _paid_by_method(receipt)
    if methods:
        story += [_row(f"Payé ({method.lower()})", amount(paid, cur)) for method, paid in methods]
    else:
        story.append(_row("Payé", amount(receipt.paid_total, cur)))
    if receipt.balance > 0 and receipt.status != "cancelled":
        story.append(_row("RESTE À PAYER", amount(receipt.balance, cur), strong=True))
    if receipt.returns:
        story.append(_dash())
        story += [
            _row(
                f"Retour n° {_short_no(item.return_no)} du {_local(item.returned_at, tz):%d/%m/%y}",
                f"-{figure(item.total_refund)}",
                right_width=16 * mm,
            )
            for item in receipt.returns
        ]
    story.append(_dash())
    if receipt.company.receipt_footer:
        story.append(pdf.para(pdf.text(receipt.company.receipt_footer), center))
    story.append(
        pdf.para("Reçu édité avec CoGes", pdf.style("t-small", size=7, mono=True, align="center"))
    )
    return pdf.build_band(
        story,
        title=f"Reçu de la vente n° {_short_no(receipt.sale_no)}",
        author=receipt.company.name,
    )


# ------------------------------------------------------------------ bon de retour


def render_return_slip(
    detail: SaleReturnDetail,
    receipt: ReceiptRead,
    lines: list[SlipLine],
    *,
    logo_png: bytes | None,
    tz: str,
) -> bytes:
    """Bon de retour, au gabarit du ticket (écran 10) : même en-tête, logo et adresse."""
    cur = receipt.company.currency
    plain = pdf.style("t-plain", size=8.5, mono=True)
    story = _ticket_header(receipt.company, logo_png)
    story += [
        _dash(),
        pdf.para(
            "BON DE RETOUR", pdf.style("t-heading", size=9, mono=True, bold=True, align="center")
        ),
        _row(
            f"Retour n° {_short_no(detail.return_no)}",
            _date_time(detail.returned_at, tz),
            right_width=34 * mm,
        ),
        pdf.para(pdf.text(f"Sur la vente n° {_short_no(receipt.sale_no)}"), plain),
    ]
    if receipt.customer:
        story.append(pdf.para(pdf.text(f"Client : {receipt.customer.name}"), plain))
    if detail.reason:
        story.append(pdf.para(pdf.text(f"Pourquoi : {detail.reason}"), plain))
    story.append(_dash())
    for line in lines:
        story.append(pdf.para(pdf.text(line.name), plain))
        story.append(
            _row(
                f"{qty(line.qty)} x {figure(line.unit_price)}",
                figure(line.refund_amount),
                indent=True,
            )
        )
    story += [_dash(), _row("VALEUR RENDUE", amount(detail.total_refund, cur), strong=True)]
    for payment in detail.payments:
        if payment.cancelled or payment.reversal_of_payment_id:
            continue
        method = PAYMENT_METHODS.get(payment.method, payment.method)
        story.append(_row(f"Réglé ({method.lower()})", amount(payment.amount, cur)))
    if detail.refund_due > 0:
        story.append(_row("RESTE À RENDRE", amount(detail.refund_due, cur), strong=True))
    story += [
        _dash(),
        pdf.para("Reçu édité avec CoGes", pdf.style("t-small", size=7, mono=True, align="center")),
    ]
    return pdf.build_band(
        story, title=f"Bon de retour n° {_short_no(detail.return_no)}", author=receipt.company.name
    )
