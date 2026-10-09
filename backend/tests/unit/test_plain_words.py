"""Mots simples (phase 15, lot 2) : les textes que le serveur produit pour l'écran.

Libellés des métriques et des séries, titres et textes d'insight, notifications et
en-têtes d'export : aucun terme de gestionnaire. Le même lexique est vérifié côté front
(`frontend/lib/plain-words.test.ts`).
"""

from __future__ import annotations

import ast
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.analytics.schemas import METRIC_LABELS, SERIES_LABELS
from app.modules.importexport.importers import IMPORTERS
from app.modules.importexport.service import SALES_HEADERS
from app.modules.intelligence.pipelines import templates

#: Terme interdit → son remplaçant (lexique du lot 2).
FORBIDDEN: dict[str, re.Pattern[str]] = {
    "CA (Ventes, Vendu)": re.compile(r"\bCA\b"),
    "chiffre d'affaires (Ventes, Vendu)": re.compile(r"chiffre d['’]affaires", re.I),
    "CMP (Prix d'achat moyen)": re.compile(r"\bCMP\b"),
    "coût des ventes (Prix d'achat des articles vendus)": re.compile(r"co[uû]t des ventes", re.I),
    "marge (Gagné sur les ventes)": re.compile(r"\bmarges?\b", re.I),
    "encaissement (Entré dans la caisse)": re.compile(r"\bencaissements?\b", re.I),
    "décaissement (Sorti de la caisse)": re.compile(r"\bd[ée]caissements?\b", re.I),
    "trésorerie (caisse)": re.compile(r"tr[ée]sorerie", re.I),
    "créance (Les clients vous doivent)": re.compile(r"cr[ée]ances?", re.I),
    "SKU (Référence)": re.compile(r"\bsku\b", re.I),
    "motif (Pourquoi ?)": re.compile(r"\bmotifs?\b", re.I),
    "échéance, échue (À payer avant le)": re.compile(r"[ée]ch[ée]ances?|\béchue?s?\b", re.I),
    "anonyme (Client de passage)": re.compile(r"anonyme", re.I),
}

DAY = date(2026, 10, 6)
NOTIFICATIONS = Path(__file__).parents[2] / "app" / "workers" / "tasks" / "notifications.py"


def _offences(text: str) -> list[str]:
    return [term for term, pattern in FORBIDDEN.items() if pattern.search(text)]


def _displayed_strings(path: Path) -> list[str]:
    """Chaînes d'un module, docstrings exclues : ce qui peut finir à l'écran."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_metric_and_series_labels() -> None:
    labels = [label for label, _unit in METRIC_LABELS.values()] + list(SERIES_LABELS.values())
    assert {label: _offences(label) for label in labels if _offences(label)} == {}
    # Huit métriques, huit noms distincts (Diagramme 7).
    assert len({label for label, _unit in METRIC_LABELS.values()}) == len(METRIC_LABELS)


def test_insight_texts() -> None:
    names = [
        templates.METRIC_STOCKOUT,
        templates.METRIC_VELOCITY,
        templates.METRIC_QUANTITY,
        templates.METRIC_MARGIN_RATE,
        templates.METRIC_OVERDUE,
        templates.METRIC_HISTORY,
        templates.METRIC_REVENUE_28D,
    ]
    rendered = [
        templates.stockout_risk("Riz", 3, Decimal("2"), DAY),
        templates.slow_mover("Riz", Decimal("0.1"), Decimal("40"), Decimal("400")),
        templates.demand_spike("Riz", DAY, Decimal("18"), "3.500", 4.2),
        templates.margin_drop("Riz", Decimal("0.21"), Decimal("0.35")),
        templates.debt_overdue("Awa Diop", 45, Decimal("25000"), DAY),
        templates.insufficient_history("Riz", 3, 1),
    ]
    texts = names + [text for pair in rendered for text in pair]
    assert {text: _offences(text) for text in texts if _offences(text)} == {}


def test_notification_texts() -> None:
    texts = _displayed_strings(NOTIFICATIONS)
    assert texts, "aucune chaîne lue"
    assert {text: _offences(text) for text in texts if _offences(text)} == {}


@pytest.mark.parametrize("kind", sorted(IMPORTERS))
def test_import_and_export_headers(kind: str) -> None:
    headers = IMPORTERS[kind].headers
    assert {header: _offences(header) for header in headers if _offences(header)} == {}
    # Des mots, pas des clés techniques : majuscule initiale, aucun souligné.
    assert all(header[0].isupper() and "_" not in header for header in headers), headers


def test_sales_export_headers() -> None:
    headers = list(SALES_HEADERS)
    assert {header: _offences(header) for header in headers if _offences(header)} == {}
    assert headers[0] == "Vente n°"
    assert all(header[0].isupper() and "_" not in header for header in headers), headers


def test_the_check_catches_an_old_term() -> None:
    assert _offences("Marge brute") == ["marge (Gagné sur les ventes)"]
    assert _offences("Dette échue") == ["échéance, échue (À payer avant le)"]
