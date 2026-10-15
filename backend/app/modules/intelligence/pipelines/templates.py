"""Gabarits des titres et textes d'insight — en français, métrique toujours nommée.

Aucune formule de classement sans métrique : ni « meilleur », ni « top », ni « best »
(décision 12). Un test parcourt ces gabarits et le vérifie.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

# Formateurs partagés avec les textes de notifications (ADR 0057).
from app.core.display import dmy, fcfa, number

#: Libellés de métrique, repris tels quels dans `evidence.metric_name`.
METRIC_STOCKOUT = "Jours avant rupture prévue"
METRIC_VELOCITY = "Vélocité des ventes"
METRIC_QUANTITY = "Quantité vendue"
METRIC_MARGIN_RATE = "Part gagnée sur les ventes"
METRIC_OVERDUE = "Retard de paiement"
METRIC_HISTORY = "Historique de ventes"
METRIC_REVENUE_28D = "Ventes générées sur 28 jours"

MAX_NAME = 80


def _name(name: str) -> str:
    return name if len(name) <= MAX_NAME else name[: MAX_NAME - 1] + "…"


def qty(value: Decimal) -> str:
    """Quantité d'un texte d'insight : une décimale au plus (ordre de grandeur, pas inventaire)."""
    return number(value, 0 if value == value.to_integral() else 1)


#: « Pour tenir deux semaines » : la commande conseillée couvre ce nombre de jours.
COVER_DAYS = 14


def stockout_risk(
    name: str, days: int, on_hand: Decimal, when: date, per_day: Decimal | None = None
) -> tuple[str, str]:
    """« Le riz va bientôt manquer » (maquette v2, écran 22 ; ADR 0074).

    Sans accord : on ne connaît pas le genre d'un article. La commande conseillée couvre
    deux semaines au rythme prévu, moins ce qui reste.
    """
    title = f"{_name(name)} : plus en stock" if days == 0 else f"{_name(name)} va bientôt manquer"
    pace = (
        f" et vous en vendez environ {qty(per_day)} par jour"
        if per_day is not None and per_day > 0
        else ""
    )
    advice = ""
    if per_day is not None and per_day > 0:
        needed = (per_day * COVER_DAYS - max(on_hand, Decimal(0))).to_integral_value()
        if needed > 0:
            advice = f" Commandez-en {qty(needed)} pour tenir deux semaines."
    body = (
        f"Il vous en reste {qty(on_hand)}{pace}. Au rythme prévu, plus rien vers le "
        f"{dmy(when)}.{advice}"
        if days > 0
        else f"Il n'en reste plus alors qu'on vous en demande.{advice or ' Commandez-en.'}"
    )
    return title, body


def slow_mover(
    name: str, velocity: Decimal, on_hand: Decimal, cover: Decimal | None
) -> tuple[str, str]:
    """« Les bougies ne bougent pas » : un article qui dort en stock."""
    title = f"{_name(name)} se vend peu"
    cover_text = (
        f"de quoi tenir {number(int(cover))} jours au rythme des 28 derniers"
        if cover is not None
        else "sans aucune vente depuis 28 jours"
    )
    body = (
        f"{qty(on_hand)} en stock, {cover_text}. "
        "Mettez cet article en avant ou faites un petit prix."
    )
    return title, body


def demand_spike(name: str, day: date, observed: Decimal, mean: str, z: float) -> tuple[str, str]:
    """« Le savon Madar se vend deux fois plus » : une journée bien au-dessus de l'habitude."""
    title = f"{_name(name)} se vend plus que d'habitude"
    body = (
        f"Le {dmy(day)}, vous en avez vendu {qty(observed)}, contre "
        f"{number(Decimal(mean), 1)} par jour d'habitude. Pensez à en garder assez."
    )
    return title, body


def margin_drop(name: str, rate_7d: Decimal, rate_28d: Decimal) -> tuple[str, str]:
    """Ce que l'article fait gagner baisse : prix de vente ou prix d'achat à revoir."""
    title = f"{_name(name)} vous rapporte moins"
    body = (
        f"Sur 7 jours, vous gardez {number(rate_7d * 100, 1)} % de ce que vous le vendez, "
        f"contre {number(rate_28d * 100, 1)} % sur 28 jours. "
        "Revoyez son prix ou son prix d'achat."
    )
    return title, body


def debt_overdue(customer: str, days: int, balance: Decimal, since: date) -> tuple[str, str]:
    """« Moussa Fall vous doit 25 000 F depuis 12 jours »."""
    title = f"{_name(customer)} vous doit {fcfa(balance)} depuis {days} jours"
    body = (
        f"À payer depuis le {dmy(since)}. "
        "Un petit rappel par WhatsApp aide souvent à se faire payer."
    )
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
