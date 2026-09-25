"""Étape 04 du Diagramme 7 : features d'un produit pour un `as_of`.

Tout ce qu'une prévision ou un insight utilisera ensuite est calculé **ici**, une
fois, puis figé dans `ml_feature_snapshots`. L'inférence ne relit que ces photographies :
elle ne peut donc pas voir une donnée postérieure à D, même par accident.

Les valeurs décimales sont écrites en chaînes, comme partout dans le projet.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.money import serialize
from app.modules.intelligence.features.series import ProductHistory

#: Seuil d'historique (ADR 0035) : 28 jours depuis la première vente **et** au moins
#: 5 jours avec des ventes sur les 60 derniers. En dessous, aucune prévision.
MIN_HISTORY_DAYS = 28
MIN_SOLD_DAYS = 5
SOLD_DAYS_WINDOW = 60

#: Profondeur de la série chargée : 60 jours pour le seuil, 56 pour l'entraînement,
#: 7 de plus pour les labels des photographies de la semaine passée.
HISTORY_WINDOW_DAYS = 90

#: Version du contenu de `features`. Un changement de clé la fait avancer.
FEATURES_SCHEMA = 1

QTY = Decimal("0.001")
AMOUNT = Decimal("0.01")
RATIO = Decimal("0.0001")


def _q(value: Decimal, exponent: Decimal) -> str:
    return serialize(value.quantize(exponent, rounding=ROUND_HALF_UP))


def _last(values: list[Decimal], n: int) -> Decimal:
    return sum(values[-n:], Decimal(0))


def _margin_rate(revenue: Decimal, cogs: Decimal) -> str | None:
    if revenue <= 0:
        return None
    return _q((revenue - cogs) / revenue, RATIO)


def is_sufficient(history_days: int, sold_days: int) -> bool:
    return history_days >= MIN_HISTORY_DAYS and sold_days >= MIN_SOLD_DAYS


def build_features(history: ProductHistory, as_of: date) -> dict[str, Any]:
    """Photographie d'un produit au soir de `as_of`."""
    qty = history.qty
    observable_prior = [
        float(value)
        for value, out in zip(qty[-29:-1], history.censored[-29:-1], strict=True)
        if not out
    ]
    mean_prior = sum(observable_prior) / len(observable_prior) if observable_prior else 0.0
    std_prior = (
        math.sqrt(
            sum((v - mean_prior) ** 2 for v in observable_prior) / max(len(observable_prior) - 1, 1)
        )
        if observable_prior
        else 0.0
    )

    dow_totals = [0.0] * 7
    dow_counts = [0] * 7
    for day, value, out in zip(history.days[-28:], qty[-28:], history.censored[-28:], strict=True):
        if out:
            continue
        dow_totals[day.weekday()] += float(value)
        dow_counts[day.weekday()] += 1
    dow_mean = [f"{dow_totals[k] / dow_counts[k]:.3f}" if dow_counts[k] else None for k in range(7)]

    qty_28d = _last(qty, 28)
    velocity = qty_28d / 28
    revenue_7d, revenue_28d = _last(history.revenue, 7), _last(history.revenue, 28)
    cogs_7d, cogs_28d = _last(history.cogs, 7), _last(history.cogs, 28)

    on_hand: Decimal | None = None
    avg_on_hand: Decimal | None = None
    rotation: str | None = None
    cover: str | None = None
    if history.on_hand is not None:
        on_hand = history.on_hand[-1]
        avg_on_hand = sum(history.on_hand[-28:], Decimal(0)) / 28
        # Un stock moyen nul rend la rotation indéfinie, pas nulle (ADR 0033).
        rotation = _q(qty_28d / avg_on_hand, RATIO) if avg_on_hand > 0 else None
        cover = _q(on_hand / velocity, RATIO) if velocity > 0 else None

    first_sale = history.first_sale_day
    history_days = (as_of - first_sale).days + 1 if first_sale else 0
    sold_days = sum(1 for value in qty[-SOLD_DAYS_WINDOW:] if value > 0)

    return {
        "schema": FEATURES_SCHEMA,
        "product_name": history.name,
        "stock_tracked": history.stock_tracked,
        "qty_1d": _q(qty[-1], QTY),
        "qty_7d": _q(_last(qty, 7), QTY),
        "qty_28d": _q(qty_28d, QTY),
        "velocity_28d": _q(velocity, QTY),
        "revenue_7d": _q(revenue_7d, AMOUNT),
        "revenue_28d": _q(revenue_28d, AMOUNT),
        "margin_7d": _q(revenue_7d - cogs_7d, AMOUNT),
        "margin_28d": _q(revenue_28d - cogs_28d, AMOUNT),
        "margin_rate_7d": _margin_rate(revenue_7d, cogs_7d),
        "margin_rate_28d": _margin_rate(revenue_28d, cogs_28d),
        "mean_prior_28d": f"{mean_prior:.3f}",
        "std_prior_28d": f"{std_prior:.3f}",
        "observable_prior_28d": len(observable_prior),
        "dow_mean_28d": dow_mean,
        "stockout_days_28d": sum(1 for out in history.censored[-28:] if out),
        "on_hand": _q(on_hand, QTY) if on_hand is not None else None,
        "avg_on_hand_28d": _q(avg_on_hand, QTY) if avg_on_hand is not None else None,
        "rotation_28d": rotation,
        "days_of_cover": cover,
        "first_sale_day": first_sale.isoformat() if first_sale else None,
        "history_days": history_days,
        "sold_days_60d": sold_days,
        "sufficient": is_sufficient(history_days, sold_days),
    }


def build_labels(history: ProductHistory, as_of: date) -> dict[str, Any] | None:
    """Réalisé des 7 jours qui suivent `as_of`, pour le backtest ; `None` s'il manque des jours.

    C'est la seule écriture différée de la table : un label est par nature connu
    après sa date, et il ne sert jamais de feature.
    """
    wanted = [as_of + timedelta(days=offset) for offset in range(1, 8)]
    positions = {day: position for position, day in enumerate(history.days)}
    if any(day not in positions for day in wanted):
        return None
    total = sum((history.qty[positions[day]] for day in wanted), Decimal(0))
    return {"qty_next_7d": _q(total, QTY), "horizon_days": 7}
