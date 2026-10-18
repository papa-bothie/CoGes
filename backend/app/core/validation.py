"""Contrôles de saisie communs aux schémas Pydantic."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel


def reject_explicit_nulls(model: BaseModel, fields: Iterable[str]) -> None:
    """Refuse `null` envoyé explicitement sur un champ qu'une mise à jour peut omettre
    mais jamais vider (ADR 0088). Sans ce contrôle, `setattr(None)` sur une colonne
    NOT NULL donnait une 500 au lieu d'un 422 qui nomme le champ."""
    for field in fields:
        if field in model.model_fields_set and getattr(model, field) is None:
            raise ValueError(f"« {field} » ne peut pas être vide.")
