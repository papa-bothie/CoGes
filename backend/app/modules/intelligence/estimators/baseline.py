"""Moyenne mobile de référence : le modèle que tout autre doit battre."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.intelligence.estimators import Z_80

MODEL_NAME = "moving_average_28"
#: Pas d'entraînement, donc pas de semaine : la formule est la version.
MODEL_VERSION = "1"
WINDOW_DAYS = 28


@dataclass(frozen=True)
class Baseline:
    """Moyenne et écart-type des jours observables de la fenêtre."""

    mean: float
    std: float
    n_obs: int

    def predict(self) -> tuple[float, float, float]:
        """`(yhat, borne basse, borne haute)` pour un jour futur, bornés à zéro."""
        spread = Z_80 * self.std
        return max(self.mean, 0.0), max(self.mean - spread, 0.0), max(self.mean + spread, 0.0)


def fit_baseline(values: Sequence[float], censored: Sequence[bool]) -> Baseline | None:
    """Moyenne mobile sur les `WINDOW_DAYS` derniers jours, ruptures exclues.

    Un jour de rupture n'est pas un jour sans demande : l'inclure tirerait la
    prévision vers zéro, et l'article manquerait encore la semaine suivante (§ 6.2).
    """
    window = [
        value
        for value, out in zip(values[-WINDOW_DAYS:], censored[-WINDOW_DAYS:], strict=True)
        if not out
    ]
    if not window:
        return None
    mean = sum(window) / len(window)
    variance = sum((value - mean) ** 2 for value in window) / max(len(window) - 1, 1)
    return Baseline(mean=mean, std=math.sqrt(variance), n_obs=len(window))
