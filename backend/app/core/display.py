"""Formatage d'affichage des textes composés côté serveur (notifications, insights).

Mêmes règles que le front (`frontend/lib/format/`, `CLAUDE.md` § 5) : espace fine
insécable pour les milliers, virgule décimale, montants en FCFA sans décimales, dates
`jj/mm/aaaa`. Ces fonctions ne servent qu'à **écrire une phrase** : une valeur que l'on
relira (champ `data`, JSON d'API) reste en `Decimal` sérialisé ou en date ISO.

V1 est mono-devise (XOF) : le libellé « FCFA » est fixe (ADR 0057).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

#: Espace fine insécable, séparateur de milliers de l'affichage (`CLAUDE.md` § 5).
THIN_NBSP = " "
#: Espace insécable entre un montant et son unité.
NBSP = " "

#: Décimales au plus d'une quantité `numeric(14, 3)`.
QTY_DECIMALS = 3


def number(value: Decimal | float, decimals: int = 0) -> str:
    """Nombre à la française : espace fine insécable pour les milliers, virgule décimale."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", THIN_NBSP).replace(".", ",")


def fcfa(value: Decimal) -> str:
    """Montant XOF arrondi à l'unité (`ROUND_HALF_UP`) : « 21 830 FCFA »."""
    rounded = int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return number(rounded) + f"{NBSP}FCFA"


def dmy(day: date) -> str:
    """Date `jj/mm/aaaa`."""
    return day.strftime("%d/%m/%Y")


def qty(value: Decimal) -> str:
    """Quantité comme le front : trois décimales au plus, zéros inutiles retirés.

    « 1.000 » → « 1 », « 12.500 » → « 12,5 », « 1500.000 » → « 1 500 ».
    """
    rounded = value.quantize(Decimal(1).scaleb(-QTY_DECIMALS), rounding=ROUND_HALF_UP)
    text = number(rounded, QTY_DECIMALS)
    return text.rstrip("0").rstrip(",") if "," in text else text
