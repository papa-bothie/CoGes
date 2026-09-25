"""Estimateurs de CoGes Intelligence : ce qu'ils promettent, sur des séries connues."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.modules.intelligence.estimators import anomaly, baseline, seasonal
from app.modules.intelligence.estimators.artifacts import ArtifactStore
from app.modules.intelligence.estimators.pareto import abc_classes
from app.modules.intelligence.features.builder import build_features, is_sufficient
from app.modules.intelligence.features.series import ProductHistory
from app.modules.intelligence.pipelines.common import uncertainty_level, week_version

START = date(2026, 7, 27)  # un lundi


def _days(n: int) -> list[date]:
    return [START + timedelta(days=k) for k in range(n)]


def test_the_baseline_ignores_stockout_days() -> None:
    values = [4.0] * 20 + [0.0] * 8
    censored = [False] * 20 + [True] * 8
    fit = baseline.fit_baseline(values, censored)
    assert fit is not None and fit.mean == 4.0 and fit.n_obs == 20
    assert baseline.fit_baseline([0.0] * 5, [True] * 5) is None


def test_the_seasonal_model_learns_the_weekly_pattern() -> None:
    pattern = [2.0, 2.0, 3.0, 3.0, 4.0, 8.0, 6.0]
    days = _days(56)
    values = [pattern[day.weekday()] for day in days]
    fit = seasonal.fit_seasonal(days, values, [False] * 56)
    assert fit is not None
    saturday = START + timedelta(days=61)
    tuesday = START + timedelta(days=57)
    assert round(fit.predict(saturday)[0], 3) == 8.0
    assert round(fit.predict(tuesday)[0], 3) == 2.0
    # Aller-retour JSON sans perte : l'artefact est la seule mémoire du modèle.
    assert seasonal.SeasonalFit.from_json(fit.to_json()) == fit


def test_the_seasonal_model_needs_enough_observable_days() -> None:
    days = _days(56)
    censored = [k % 3 != 0 for k in range(56)]
    assert seasonal.fit_seasonal(days, [1.0] * 56, censored) is None


def test_predictions_are_never_negative() -> None:
    days = _days(28)
    declining = [float(28 - k) for k in range(28)]
    fit = seasonal.fit_seasonal(days, declining, [False] * 28)
    assert fit is not None
    yhat, lower, upper = fit.predict(START + timedelta(days=90))
    assert yhat >= 0 and lower >= 0 and upper >= lower


def test_zscore_is_undefined_on_a_flat_series() -> None:
    assert anomaly.zscore(5, 5, 0) is None
    assert anomaly.zscore(11, 5, 2) == 3.0


def test_pareto_classes_follow_the_named_metric() -> None:
    classes = abc_classes(
        {"a": Decimal(800), "b": Decimal(150), "c": Decimal(40), "d": Decimal(10), "e": Decimal(0)}
    )
    assert classes == {"a": "A", "b": "B", "c": "C", "d": "C", "e": "C"}


def test_the_history_threshold() -> None:
    assert is_sufficient(28, 5)
    assert not is_sufficient(27, 60)
    assert not is_sufficient(400, 4)


def test_the_dense_series_counts_empty_days_as_zero() -> None:
    days = _days(90)
    qty = [Decimal(0)] * 90
    for k in (89, 80, 70):
        qty[k] = Decimal(6)
    history = ProductHistory(
        product_id=uuid4(),
        name="Test",
        stock_tracked=False,
        days=days,
        qty=qty,
        revenue=[q * 1000 for q in qty],
        cogs=[q * 600 for q in qty],
        on_hand=None,
        censored=[False] * 90,
        first_sale_day=days[70],
    )
    features = build_features(history, days[-1])
    assert features["qty_28d"] == "18.000"
    assert features["velocity_28d"] == "0.643"  # 18 / 28 : les jours vides comptent
    assert features["sold_days_60d"] == 3
    assert features["history_days"] == 20
    assert features["sufficient"] is False
    assert features["on_hand"] is None and features["rotation_28d"] is None
    assert features["margin_rate_28d"] == "0.4000"


def test_artifacts_round_trip(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    company = uuid4()
    path = store.save(company, "seasonal_ols", "2026-W39", {"products": {"x": [1, 2]}})
    assert path == tmp_path / str(company) / "seasonal_ols" / "2026-W39.json"
    assert store.load(company, "seasonal_ols", "2026-W39") == {"products": {"x": [1, 2]}}
    assert store.load(company, "seasonal_ols", "2026-W40") is None


def test_versions_and_uncertainty() -> None:
    # Lundi 21/09/2026 : as_of = dimanche 20/09, la version est celle de la semaine
    # qui commence le lundi du calcul.
    assert week_version(date(2026, 9, 20)) == "2026-W39"
    assert week_version(date(2026, 9, 26)) == "2026-W39"
    assert uncertainty_level(10, 8, 12) == "faible"
    assert uncertainty_level(10, 6, 15) == "moyenne"
    assert uncertainty_level(1, 0, 5) == "élevée"
