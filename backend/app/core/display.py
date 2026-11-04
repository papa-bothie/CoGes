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


#: Unités au singulier et au pluriel (révision 0015).
UNITS: dict[str, tuple[str, str]] = {
    "piece": ("pièce", "pièces"),
    "kg": ("kg", "kg"),
    "litre": ("litre", "litres"),
    "carton": ("carton", "cartons"),
    "metre": ("mètre", "mètres"),
    "paquet": ("paquet", "paquets"),
    "sac": ("sac", "sacs"),
    "bouteille": ("bouteille", "bouteilles"),
}


def qty_with_unit(value: Decimal, unit: str) -> str:
    """« 3 sacs », « 1 sac », « 2,5 kg » : la quantité suivie de son unité accordée."""
    singular, plural = UNITS.get(unit, ("", ""))
    word = singular if value <= 1 else plural
    return f"{qty(value)} {word}".rstrip()


# --------------------------------------------------------------- pièces imprimées
# Formats du reçu à l'écran (`frontend/lib/format/money.ts`), repris par les PDF du
# serveur (ADR 0113) : « 87 500 F », espace insécable pleine entre les milliers.

#: Libellé court de la devise, comme la maquette v2 (« 87 500 F »).
SHORT_CURRENCY = {"XOF": "F"}


def figure(value: Decimal) -> str:
    """Montant sans unité, arrondi à l'unité : « 15 500 » (colonne du ticket)."""
    rounded = int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return number(rounded).replace(THIN_NBSP, NBSP)


def amount(value: Decimal, currency: str = "XOF") -> str:
    """Montant du reçu : « 87 500 F »."""
    return f"{figure(value)}{NBSP}{SHORT_CURRENCY.get(currency, currency)}"


_WORDS = [
    "zéro",
    "un",
    "deux",
    "trois",
    "quatre",
    "cinq",
    "six",
    "sept",
    "huit",
    "neuf",
    "dix",
    "onze",
    "douze",
    "treize",
    "quatorze",
    "quinze",
    "seize",
]
_TENS = ("", "dix", "vingt", "trente", "quarante", "cinquante", "soixante")


def _below_hundred(value: int, final: bool) -> str:
    if value <= 16:
        return _WORDS[value]
    if value < 20:
        return f"dix-{_WORDS[value - 10]}"
    if value < 70:
        tens, unit = divmod(value, 10)
        if unit == 0:
            return _TENS[tens]
        return f"{_TENS[tens]} et un" if unit == 1 else f"{_TENS[tens]}-{_WORDS[unit]}"
    if value < 80:
        return (
            "soixante et onze" if value == 71 else f"soixante-{_below_hundred(value - 60, final)}"
        )
    if value == 80:
        return "quatre-vingts" if final else "quatre-vingt"
    return f"quatre-vingt-{_below_hundred(value - 80, final)}"


def _below_thousand(value: int, final: bool) -> str:
    hundreds, rest = divmod(value, 100)
    parts: list[str] = []
    if hundreds > 0:
        plural = hundreds > 1 and rest == 0 and final
        parts.append("cent" if hundreds == 1 else f"{_WORDS[hundreds]} cent{'s' if plural else ''}")
    if rest > 0 or hundreds == 0:
        parts.append(_below_hundred(rest, final))
    return " ".join(parts)


def number_in_words(value: int) -> str:
    """Entier positif en toutes lettres, orthographe traditionnelle, comme le front."""
    if value == 0:
        return _WORDS[0]
    parts: list[str] = []
    rest = value
    for scale, name in ((1_000_000_000, "milliard"), (1_000_000, "million")):
        count, rest = divmod(rest, scale)
        if count > 0:
            parts.append(f"{number_in_words(count)} {name}{'s' if count > 1 else ''}")
    thousands, units = divmod(rest, 1000)
    if thousands > 0:
        parts.append("mille" if thousands == 1 else f"{_below_thousand(thousands, False)} mille")
    if units > 0:
        parts.append(_below_thousand(units, True))
    return " ".join(parts)


def amount_in_words(value: Decimal) -> str:
    """« vingt-cinq mille francs CFA » : la partie entière, comme la facture à l'écran."""
    whole = int(value)
    return f"{number_in_words(whole)} franc{'s' if whole > 1 else ''} CFA"


#: Moyens de paiement en mots, comme `labels.paymentMethods` du front.
PAYMENT_METHODS = {
    "cash": "Espèces",
    "wave": "Wave",
    "orange_money": "Orange Money",
    "mobile_money": "Mobile money",
    "bank_transfer": "Virement",
    "card": "Carte",
    "cheque": "Chèque",
    "offset": "Compensation de dette",
}
