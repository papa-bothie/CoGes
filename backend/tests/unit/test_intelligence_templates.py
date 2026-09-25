"""Contrôle de libellé : aucun classement sans métrique nommée (décision 12).

Tous les gabarits sont appelés avec des valeurs plausibles et extrêmes ; aucun titre
ni texte ne contient « meilleur », « best » ou « top ». Les titres tiennent dans les
160 caractères du `CHECK` de `insights.title`, même avec un nom de produit démesuré.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from app.modules.intelligence.pipelines import templates

FORBIDDEN = re.compile(r"\b(meilleure?s?|best|top)\b", re.IGNORECASE)
DAY = date(2026, 9, 24)
LONG = "Produit au nom très long " * 12


def _renders(name: str) -> list[tuple[str, str]]:
    return [
        templates.stockout_risk(name, 0, Decimal("0"), DAY),
        templates.stockout_risk(name, 1, Decimal("3"), DAY),
        templates.stockout_risk(name, 6, Decimal("20.5"), DAY),
        templates.slow_mover(name, Decimal("0.107"), Decimal("400"), Decimal("3733")),
        templates.slow_mover(name, Decimal("0"), Decimal("12"), None),
        templates.demand_spike(name, DAY, Decimal("18"), "3.500", 4.2),
        templates.margin_drop(name, Decimal("0.21"), Decimal("0.35")),
        templates.debt_overdue(name, 45, Decimal("1234567"), DAY),
        templates.insufficient_history(name, 3, 1),
    ]


@pytest.mark.parametrize("name", ["Riz parfumé 5 kg", LONG, "Top Café"])
def test_templates_never_rank_without_a_metric(name: str) -> None:
    assert len(templates.TEMPLATES) == 6
    for title, body in _renders(name):
        # Le nom du produit est une donnée saisie, pas une formule du gabarit.
        assert not FORBIDDEN.search(title.replace(name[: templates.MAX_NAME], "")), title
        assert not FORBIDDEN.search(body.replace(name, "")), body
        assert 1 <= len(title.strip()) <= 160, title


def test_metric_labels_are_named() -> None:
    labels = [
        templates.METRIC_STOCKOUT,
        templates.METRIC_VELOCITY,
        templates.METRIC_QUANTITY,
        templates.METRIC_MARGIN_RATE,
        templates.METRIC_OVERDUE,
        templates.METRIC_HISTORY,
        templates.METRIC_REVENUE_28D,
    ]
    assert len(set(labels)) == len(labels)
    for label in labels:
        assert not FORBIDDEN.search(label)


def test_amounts_are_displayed_the_french_way() -> None:
    assert templates.fcfa(Decimal("1234567.40")) == "1 234 567 FCFA"
    assert templates.dmy(DAY) == "24/09/2026"
