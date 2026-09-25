"""Z-score : écart d'une observation à la moyenne, en écarts-types."""

from __future__ import annotations


def zscore(value: float, mean: float, std: float) -> float | None:
    """`None` si l'écart-type est nul : une série constante n'a pas d'anomalie mesurable."""
    if std <= 0:
        return None
    return (value - mean) / std
