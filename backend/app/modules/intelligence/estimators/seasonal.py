"""Régression saisonnière hebdomadaire : tendance + jour de la semaine (OLS).

Le modèle le plus simple qui capte ce qu'une boutique vit vraiment : le samedi n'est
pas le mardi. Ajusté par produit sur les jours observables, il produit un intervalle
de prédiction à 80 % à partir de la variance résiduelle et de la covariance des
coefficients.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import statsmodels.api as sm

from app.modules.intelligence.estimators import Z_80

MODEL_NAME = "seasonal_ols"
#: Fenêtre d'entraînement. Huit semaines donnent huit observations par jour de semaine.
TRAIN_WINDOW_DAYS = 56
#: En dessous, sept coefficients de jour et une tendance sont sur-ajustés.
MIN_OBSERVATIONS = 21


def _design(day_index: float, weekday: int) -> list[float]:
    """Constante, tendance, six indicatrices (lundi en référence)."""
    return [1.0, day_index] + [1.0 if weekday == k else 0.0 for k in range(1, 7)]


@dataclass(frozen=True)
class SeasonalFit:
    """Coefficients sérialisables : l'artefact est du JSON, jamais du pickle."""

    origin: date
    params: list[float]
    cov: list[list[float]]
    sigma2: float
    n_obs: int
    r2: float

    def predict(self, day: date) -> tuple[float, float, float]:
        """`(yhat, borne basse, borne haute)` pour `day`, bornés à zéro."""
        x = np.array(_design(float((day - self.origin).days), day.weekday()))
        params = np.array(self.params)
        cov = np.array(self.cov)
        yhat = float(x @ params)
        spread = Z_80 * math.sqrt(max(self.sigma2 + float(x @ cov @ x), 0.0))
        return max(yhat, 0.0), max(yhat - spread, 0.0), max(yhat + spread, 0.0)

    def to_json(self) -> dict[str, Any]:
        return {
            "origin": self.origin.isoformat(),
            "params": self.params,
            "cov": self.cov,
            "sigma2": self.sigma2,
            "n_obs": self.n_obs,
            "r2": self.r2,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> SeasonalFit:
        return cls(
            origin=date.fromisoformat(str(payload["origin"])),
            params=[float(v) for v in payload["params"]],
            cov=[[float(v) for v in row] for row in payload["cov"]],
            sigma2=float(payload["sigma2"]),
            n_obs=int(payload["n_obs"]),
            r2=float(payload["r2"]),
        )


def fit_seasonal(
    days: Sequence[date], values: Sequence[float], censored: Sequence[bool]
) -> SeasonalFit | None:
    """Ajuste le modèle sur les jours observables ; `None` s'il y en a trop peu.

    Les jours de rupture sont écartés comme demande censurée (§ 6.2). La tendance est
    comptée en jours depuis le premier jour de la fenêtre.
    """
    window = list(zip(days, values, censored, strict=True))[-TRAIN_WINDOW_DAYS:]
    observed = [(day, value) for day, value, out in window if not out]
    if len(observed) < MIN_OBSERVATIONS:
        return None
    origin = window[0][0]
    x = np.array([_design(float((day - origin).days), day.weekday()) for day, _ in observed])
    y = np.array([value for _, value in observed])
    # Une série constante a une variance totale nulle : R² n'est pas défini, et
    # statsmodels le dit par un avertissement de division. C'est attendu, pas un bug.
    with np.errstate(divide="ignore", invalid="ignore"):
        result = sm.OLS(y, x).fit()
        sigma2 = float(result.scale) if np.isfinite(result.scale) else 0.0
        cov = np.nan_to_num(np.asarray(result.cov_params()), nan=0.0)
        r2 = float(result.rsquared) if np.isfinite(result.rsquared) else 0.0
    return SeasonalFit(
        origin=origin,
        params=[float(v) for v in np.nan_to_num(np.asarray(result.params), nan=0.0)],
        cov=[[float(v) for v in row] for row in cov],
        sigma2=sigma2,
        n_obs=len(observed),
        r2=r2,
    )
