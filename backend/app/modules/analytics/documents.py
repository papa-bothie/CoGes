"""Mise en page des exports PDF pour le comptable (prompt 35, bloc X, ADR 0114).

Fonctions **pures** : un rapport de `reports.py` entre, des octets sortent. Chaque document
porte le même en-tête (logo, boutique, adresse, NINEA, titre, période, « Édité le … par
… »), des totaux, « Page n/N » et le pied « Document généré par CoGes ».
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from reportlab.lib.units import mm
from reportlab.platypus import Flowable, KeepTogether, Spacer, Table, TableStyle

from app.core import pdf
from app.core.display import PAYMENT_METHODS, amount, dmy, qty_with_unit
from app.modules.analytics.reports import (
    AGING_BUCKETS,
    CashReport,
    DebtsReport,
    ExpensesReport,
    Masthead,
    SalesReport,
    StockReport,
    cash_line_label,
)

FOOTER = "Document généré par CoGes"
WIDTH = pdf.A4_CONTENT_WIDTH


def _minus(value: Decimal, currency: str) -> str:
    """Un montant retranché : « -1 500 F », mais « 0 F » quand il n'y a rien."""
    return f"-{amount(value, currency)}" if value else amount(value, currency)


def _short(document_no: str) -> str:
    digits = document_no.rsplit("-", 1)[-1]
    return str(int(digits)) if digits.isdigit() else document_no


def _period(head: Masthead) -> str:
    if head.period_from is None or head.period_to is None:
        return f"À la date du {dmy(head.edited_at.date())}"
    if head.period_from == head.period_to:
        return f"Le {dmy(head.period_from)}"
    return f"Du {dmy(head.period_from)} au {dmy(head.period_to)}"


def _header(head: Masthead, title: str) -> list[Flowable]:
    base = pdf.style("x-base", size=9)
    grey = pdf.style("x-grey", size=8.5, color=pdf.GREY)
    right = pdf.style("x-right", size=9, align="right")
    shop: list[Flowable] = [
        pdf.para(pdf.text(head.company_name), pdf.style("x-shop", size=13, bold=True))
    ]
    if head.address:
        shop.append(pdf.para(pdf.text(head.address), pdf.style("x-address", size=9.5, bold=True)))
    if head.phone:
        shop.append(pdf.para(pdf.text(f"Tél. {head.phone}"), base))
    ids = " · ".join(
        p for p in (head.ninea and f"NINEA {head.ninea}", head.rc and f"RC {head.rc}") if p
    )
    if ids:
        shop.append(pdf.para(pdf.text(ids), grey))
    meta: list[Flowable] = [
        pdf.para(pdf.text(title), pdf.style("x-title", size=14, bold=True, align="right")),
        pdf.para(pdf.text(_period(head)), pdf.style("x-period", size=10, bold=True, align="right")),
        pdf.para(
            pdf.text(f"Édité le {head.edited_at:%d/%m/%Y à %H:%M}"),
            right,
        ),
    ]
    if head.edited_by:
        meta.append(pdf.para(pdf.text(f"par {head.edited_by}"), right))
    image = pdf.logo(head.logo_png, max_width=20 * mm, max_height=20 * mm)
    logo_width = 23 * mm if image else 0
    cells: list[object] = ([image] if image else []) + [shop, meta]
    widths = ([logo_width] if image else []) + [WIDTH - logo_width - 72 * mm, 72 * mm]
    return [
        Table(
            [cells],
            colWidths=widths,
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("LINEBELOW", (0, 0), (-1, 0), 1.5, pdf.INK),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            ),
        ),
        Spacer(1, 5 * mm),
    ]


def _heading(text: str) -> Flowable:
    return pdf.para(
        pdf.text(text.upper()), pdf.style("x-heading", size=8.5, bold=True, color=pdf.GREY)
    )


def _table(
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    widths: Sequence[float],
    *,
    numeric_from: int,
    total: Sequence[str] | None = None,
) -> Table:
    """Tableau à en-tête répété ; colonnes numériques alignées à droite ; ligne de total."""
    cell = pdf.style("x-cell", size=8.5)
    cell_right = pdf.style("x-cell-right", size=8.5, align="right")
    head_left = pdf.style("x-head", size=7.5, bold=True, color=pdf.GREY)
    head_right = pdf.style("x-head-right", size=7.5, bold=True, color=pdf.GREY, align="right")
    bold = pdf.style("x-total", size=8.5, bold=True)
    bold_right = pdf.style("x-total-right", size=8.5, bold=True, align="right")

    def line(values: Sequence[str], left: object, right: object) -> list[object]:
        return [
            pdf.para(pdf.text(value), right if index >= numeric_from else left)  # type: ignore[arg-type]
            for index, value in enumerate(values)
        ]

    data = [line([h.upper() for h in header], head_left, head_right)]
    data += [line(row, cell, cell_right) for row in rows]
    styles: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), pdf.HEAD_FILL),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, pdf.INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, pdf.RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if total is not None:
        data.append(line(total, bold, bold_right))
        styles.append(("LINEABOVE", (0, -1), (-1, -1), 1.2, pdf.INK))
    return Table(data, colWidths=list(widths), repeatRows=1, style=TableStyle(styles))


def _totals(rows: Sequence[tuple[str, str, bool]]) -> Flowable:
    """Bloc de totaux aligné à droite : (libellé, montant, en gras)."""
    data = [
        [
            pdf.para(
                pdf.text(label), pdf.style("x-tl-b" if strong else "x-tl", size=9, bold=strong)
            ),
            pdf.para(
                pdf.text(value),
                pdf.style("x-tr-b" if strong else "x-tr", size=9, bold=strong, align="right"),
            ),
        ]
        for label, value, strong in rows
    ]
    return KeepTogether([Table(data, colWidths=[60 * mm, 35 * mm], hAlign="RIGHT")])


def _empty(text: str) -> Flowable:
    return pdf.para(pdf.text(text), pdf.style("x-empty", size=9.5, color=pdf.GREY))


def _build(head: Masthead, title: str, story: list[Flowable]) -> bytes:
    return pdf.build_a4(
        [*_header(head, title), *story],
        title=f"{title} — {_period(head)}",
        author=head.company_name,
        footer_left=FOOTER,
    )


# --------------------------------------------------------------------------- ventes


def render_sales(report: SalesReport) -> bytes:
    cur = report.masthead.currency
    story: list[Flowable] = []
    if not report.lines:
        story.append(_empty("Aucune vente sur la période."))
    else:
        story += [
            _heading("Ventes"),
            Spacer(1, 1.5 * mm),
            _table(
                ["N°", "Date", "Client", "Total", "Payé", "Reste", "Moyen"],
                [
                    [
                        _short(line.sale_no),
                        f"{line.sold_at:%d/%m/%y %H:%M}",
                        line.customer or "—",
                        amount(line.total, cur),
                        amount(line.paid, cur),
                        amount(line.remaining, cur),
                        line.methods,
                    ]
                    for line in report.lines
                ],
                [11 * mm, 25 * mm, WIDTH - 133 * mm, 23 * mm, 23 * mm, 21 * mm, 30 * mm],
                numeric_from=3,
                total=[
                    "",
                    f"{len(report.lines)} ventes",
                    "",
                    amount(report.total, cur),
                    amount(report.paid, cur),
                    amount(report.remaining, cur),
                    "",
                ],
            ),
            Spacer(1, 5 * mm),
            _heading("Par jour"),
            Spacer(1, 1.5 * mm),
            _table(
                ["Jour", "Ventes", "Total"],
                [[dmy(day), str(count), amount(total, cur)] for day, count, total in report.by_day],
                [WIDTH - 70 * mm, 30 * mm, 40 * mm],
                numeric_from=1,
            ),
            Spacer(1, 5 * mm),
            _heading("Encaissé à la vente, par moyen"),
            Spacer(1, 1.5 * mm),
            _table(
                ["Moyen", "Montant"],
                [[method, amount(total, cur)] for method, total in report.by_method]
                + (
                    [["Réglé ensuite sur la dette", amount(report.settled_later, cur)]]
                    if report.settled_later
                    else []
                ),
                [WIDTH - 40 * mm, 40 * mm],
                numeric_from=1,
            ),
        ]
    story += [
        Spacer(1, 5 * mm),
        _totals(
            [
                ("Sous-total", amount(report.subtotal, cur), False),
                ("Remises", _minus(report.discounts, cur), False),
                ("TVA", amount(report.taxes, cur), False),
                ("Total des ventes", amount(report.total, cur), True),
                ("Retours", _minus(report.returned, cur), False),
                ("Total net", amount(report.net, cur), True),
                ("Payé", amount(report.paid, cur), False),
                ("Reste dû", amount(report.remaining, cur), False),
            ]
        ),
    ]
    if report.cancelled_count:
        story.append(
            _empty(f"Ventes annulées sur la période (non comptées) : {report.cancelled_count}.")
        )
    return _build(report.masthead, "Ventes", story)


# --------------------------------------------------------------------------- caisse


def render_cash(report: CashReport) -> bytes:
    cur = report.masthead.currency
    story: list[Flowable] = [
        _totals(
            [
                ("Solde de début", amount(report.opening, cur), True),
                ("Entrées", amount(report.cash_in, cur), False),
                ("Sorties", _minus(report.cash_out, cur), False),
                ("Solde de fin", amount(report.closing, cur), True),
            ]
        ),
        Spacer(1, 2 * mm),
        _empty("Les compensations de dette, qui ne touchent pas la caisse, sont exclues."),
        Spacer(1, 4 * mm),
    ]
    if report.by_method:
        story += [
            _heading("Par moyen de paiement (entré moins sorti)"),
            Spacer(1, 1.5 * mm),
            _table(
                ["Moyen", "Net"],
                [[method, amount(net, cur)] for method, net in report.by_method],
                [WIDTH - 40 * mm, 40 * mm],
                numeric_from=1,
            ),
            Spacer(1, 5 * mm),
            _heading("Par jour"),
            Spacer(1, 1.5 * mm),
            _table(
                ["Jour", "Entrées", "Sorties", "Net"],
                [
                    [
                        dmy(day),
                        amount(cash_in, cur),
                        amount(cash_out, cur),
                        amount(cash_in - cash_out, cur),
                    ]
                    for day, cash_in, cash_out in report.by_day
                ],
                [WIDTH - 105 * mm, 35 * mm, 35 * mm, 35 * mm],
                numeric_from=1,
                total=[
                    "Total",
                    amount(report.cash_in, cur),
                    amount(report.cash_out, cur),
                    amount(report.cash_in - report.cash_out, cur),
                ],
            ),
            Spacer(1, 5 * mm),
        ]
    if not report.lines:
        story.append(_empty("Aucune entrée ni sortie d'argent sur la période."))
    else:
        zone = report.masthead.edited_at.tzinfo
        story += [
            _heading("Détail"),
            Spacer(1, 1.5 * mm),
            _table(
                ["Date", "Opération", "Moyen", "Montant"],
                [
                    [
                        f"{line.paid_at.astimezone(zone):%d/%m/%y %H:%M}",
                        cash_line_label(line),
                        PAYMENT_METHODS.get(line.method, line.method),
                        amount(line.signed_amount, cur),
                    ]
                    for line in report.lines
                ],
                [27 * mm, WIDTH - 92 * mm, 33 * mm, 32 * mm],
                numeric_from=3,
            ),
            Spacer(1, 1.5 * mm),
            _empty("Une ligne annulée et son annulation sont listées sans être comptées."),
        ]
    return _build(report.masthead, "Journal de caisse", story)


# ---------------------------------------------------------------------------- stock


def render_stock(report: StockReport) -> bytes:
    cur = report.masthead.currency
    story: list[Flowable] = []
    if not report.lines:
        story.append(_empty("Aucun article."))
    else:
        story.append(
            _table(
                ["Article", "Rayon", "Quantité", "Coût moyen", "Valeur"],
                [
                    [
                        line.name,
                        line.category,
                        qty_with_unit(line.qty, line.unit) if line.tracked else "non suivi",
                        amount(line.avg_cost, cur),
                        amount(line.value, cur),
                    ]
                    for line in report.lines
                ],
                [WIDTH - 133 * mm, 40 * mm, 30 * mm, 30 * mm, 33 * mm],
                numeric_from=2,
                total=["Valeur totale du stock", "", "", "", amount(report.total_value, cur)],
            )
        )
    story += [
        Spacer(1, 3 * mm),
        _empty("Valeur au coût moyen pondéré (CMP), à la date et à l'heure d'édition."),
    ]
    return _build(report.masthead, "État du stock", story)


# ------------------------------------------------------------------------- dépenses


def render_expenses(report: ExpensesReport) -> bytes:
    cur = report.masthead.currency
    story: list[Flowable] = []
    if not report.lines:
        story.append(_empty("Aucune dépense sur la période."))
    else:
        story += [
            _heading("Par type"),
            Spacer(1, 1.5 * mm),
            _table(
                ["Type de dépense", "Total"],
                [[name, amount(total, cur)] for name, total in report.by_category],
                [WIDTH - 40 * mm, 40 * mm],
                numeric_from=1,
                total=["Total général", amount(report.total, cur)],
            ),
            Spacer(1, 5 * mm),
            _heading("Détail"),
            Spacer(1, 1.5 * mm),
            _table(
                ["N°", "Date", "Type", "Libellé", "Montant"],
                [
                    [
                        _short(line.expense_no),
                        dmy(line.spent_at),
                        line.category,
                        line.label,
                        amount(line.amount, cur),
                    ]
                    for line in report.lines
                ],
                [14 * mm, 22 * mm, 40 * mm, WIDTH - 108 * mm, 32 * mm],
                numeric_from=4,
                total=["", "", "", "Total général", amount(report.total, cur)],
            ),
        ]
    return _build(report.masthead, "Dépenses par type", story)


# ---------------------------------------------------------------------------- dettes


def render_debts(report: DebtsReport) -> bytes:
    cur = report.masthead.currency
    labels = [label for label, _ in AGING_BUCKETS]
    story: list[Flowable] = []
    for section in report.sections:
        story += [_heading(section.title), Spacer(1, 1.5 * mm)]
        if not section.parties:
            story += [_empty("Personne."), Spacer(1, 5 * mm)]
            continue
        story += [
            _table(
                ["Nom", "Depuis le", *labels, "Total"],
                [
                    [
                        party.name or "—",
                        dmy(party.since),
                        *[amount(value, cur) if value else "" for value in party.buckets],
                        amount(party.total, cur),
                    ]
                    for party in section.parties
                ],
                [WIDTH - 134 * mm, 21 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 25 * mm],
                numeric_from=2,
                total=[
                    "Total",
                    "",
                    *[amount(v, cur) for v in section.buckets],
                    amount(section.total, cur),
                ],
            ),
            Spacer(1, 6 * mm),
        ]
    story.append(
        _empty(
            "Ancienneté comptée depuis la naissance de chaque dette, au "
            f"{dmy(report.today)} ; dettes ouvertes ou en partie payées seulement."
        )
    )
    return _build(report.masthead, "Dettes clients et fournisseurs", story)


def filename(kind: str, head: Masthead) -> str:
    """« Ventes-2026-11-01-au-2026-11-30-Boutique-Keur-Fatou.pdf »."""
    names = {
        "sales": "Ventes",
        "cash": "Caisse",
        "stock": "Stock",
        "expenses": "Depenses",
        "debts": "Dettes",
    }
    if head.period_from and head.period_to:
        when = f"{head.period_from.isoformat()}-au-{head.period_to.isoformat()}"
    else:
        when = head.edited_at.date().isoformat()
    return f"{names[kind]}-{when}-{pdf.slug(head.company_name)}.pdf"
