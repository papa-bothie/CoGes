"""Gabarits des titres et textes d'insight — en français, métrique toujours nommée.

Aucune formule de classement sans métrique : ni « meilleur », ni « top », ni « best »
(décision 12). Un test parcourt ces gabarits et le vérifie.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

#: Espace fine insécable, séparateur de milliers de l'affichage (`CLAUDE.md` § 5).
THIN_NBSP = " "

#: Libellés de métrique, repris tels quels dans `evidence.metric_name`.
METRIC_STOCKOUT = "Jours avant rupture prévue"
METRIC_VELOCITY = "Vélocité des ventes"
METRIC_QUANTITY = "Quantité vendue"
METRIC_MARGIN_RATE = "Taux de marge générée"
METRIC_OVERDUE = "Retard de paiement"
METRIC_HISTORY = "Historique de ventes"
METRIC_REVENUE_28D = "Chiffre d'affaires généré sur 28 jours"

MAX_NAME = 80


def _name(name: str) -> str:
    return name if len(name) <= MAX_NAME else name[: MAX_NAME - 1] + "…"


def fcfa(value: Decimal) -> str:
    rounded = int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return f"{rounded:,}".replace(",", THIN_NBSP) + f"{THIN_NBSP}FCFA"


def dmy(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def qty(value: Decimal) -> str:
    return f"{value.normalize():f}" if value == value.to_integral() else f"{value:.1f}"


def stockout_risk(name: str, days: int, on_hand: Decimal, when: date) -> tuple[str, str]:
    title = (
        f"Rupture en cours — {_name(name)}"
        if days == 0
        else f"Rupture prévue dans {days} jour{'s' if days > 1 else ''} — {_name(name)}"
    )
    body = (
        f"Au rythme de vente prévu, le stock de {qty(on_hand)} sera épuisé vers le "
        f"{dmy(when)}. Réapprovisionner."
        if days > 0
        else "Le stock est à zéro alors que la demande prévue ne l'est pas. Réapprovisionner."
    )
    return title, body


def slow_mover(
    name: str, velocity: Decimal, on_hand: Decimal, cover: Decimal | None
) -> tuple[str, str]:
    title = f"Écoulement lent — {_name(name)}"
    cover_text = (
        f"soit {int(cover)} jours de couverture"
        if cover is not None
        else "sans aucune vente sur 28 jours"
    )
    body = (
        f"{METRIC_VELOCITY} : {velocity} unité/jour sur 28 jours pour {qty(on_hand)} en stock, "
        f"{cover_text}. Surveiller le réassort ou revoir le prix."
    )
    return title, body


def demand_spike(name: str, day: date, observed: Decimal, mean: str, z: float) -> tuple[str, str]:
    title = f"Demande inhabituelle — {_name(name)}"
    body = (
        f"{METRIC_QUANTITY} le {dmy(day)} : {qty(observed)}, contre {mean} par jour en "
        f"moyenne sur les 28 jours précédents (écart de {z:.1f} écarts-types)."
    )
    return title, body


def margin_drop(name: str, rate_7d: Decimal, rate_28d: Decimal) -> tuple[str, str]:
    title = f"Marge en baisse — {_name(name)}"
    body = (
        f"{METRIC_MARGIN_RATE} : {rate_7d * 100:.1f} % sur 7 jours, contre "
        f"{rate_28d * 100:.1f} % sur 28 jours. Revoir le prix ou le coût d'achat."
    )
    return title, body


def debt_overdue(customer: str, days: int, balance: Decimal, since: date) -> tuple[str, str]:
    title = f"Créance en retard de {days} jours — {_name(customer)}"
    body = f"{fcfa(balance)} restent dus depuis le {dmy(since)}. Relancer le client."
    return title, body


def insufficient_history(name: str, history_days: int, sold_days: int) -> tuple[str, str]:
    title = f"Données insuffisantes — {_name(name)}"
    body = (
        f"{history_days} jour(s) depuis la première vente et {sold_days} jour(s) de vente sur "
        "les 60 derniers : il en faut au moins 28 et 5. Aucune prévision n'est produite "
        "pour ce produit."
    )
    return title, body


#: Tous les gabarits, pour le contrôle de libellé.
TEMPLATES = (
    stockout_risk,
    slow_mover,
    demand_spike,
    margin_drop,
    debt_overdue,
    insufficient_history,
)
