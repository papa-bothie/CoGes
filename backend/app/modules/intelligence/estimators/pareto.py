"""Classement ABC-Pareto sur une métrique **nommée** par l'appelant.

A : les produits qui cumulent les premiers 80 % de la métrique ; B : jusqu'à 95 % ;
C : le reste, y compris ceux qui n'ont rien généré. Le classement ne dit rien d'autre
que la métrique qu'on lui donne (décision 12).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

A_SHARE = Decimal("0.80")
B_SHARE = Decimal("0.95")


def abc_classes[K](values: Mapping[K, Decimal]) -> dict[K, str]:
    total = sum((value for value in values.values() if value > 0), Decimal(0))
    classes: dict[K, str] = {}
    cumulative = Decimal(0)
    for key, value in sorted(values.items(), key=lambda item: item[1], reverse=True):
        if total <= 0 or value <= 0:
            classes[key] = "C"
            continue
        share_before = cumulative / total
        cumulative += value
        if share_before < A_SHARE:
            classes[key] = "A"
        elif share_before < B_SHARE:
            classes[key] = "B"
        else:
            classes[key] = "C"
    return classes
