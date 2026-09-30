"""Schémas du module Companies."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Réglages booléens connus ; absents, ils valent « activé » (ADR 0022, 0036).
BOOLEAN_SETTINGS = ("tax_enabled", "intelligence_enabled")
#: Seuil d'alerte appliqué à un produit suivi créé sans seuil (ADR 0054).
DEFAULT_REORDER_POINT = "default_reorder_point"
#: Même borne que `products.reorder_point` : `numeric(14,3)`.
_MAX_REORDER = Decimal("99999999999.999")


def _checked_reorder_point(value: Any) -> str | None:
    if value is None:
        return None
    # Chaîne décimale seulement : jamais de float pour une quantité (CLAUDE.md § 4).
    if not isinstance(value, str):
        raise ValueError('Le seuil par défaut s\'envoie en chaîne décimale, par exemple "5".')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Seuil par défaut illisible.") from exc
    exponent = number.as_tuple().exponent
    if (
        not number.is_finite()
        or number < 0
        or number > _MAX_REORDER
        or (isinstance(exponent, int) and exponent < -3)
    ):
        raise ValueError("Seuil par défaut : un nombre positif, trois décimales au plus.")
    return str(number)


class CompanyRead(BaseModel):
    """Vue publique de l'entreprise courante."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    name: str
    slug: str
    currency: str
    timezone: str
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CompanyUpdate(BaseModel):
    """Paramètres modifiables. Chaque modification est auditée en transactionnel."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    #: Remplace l'objet entier : l'appelant renvoie les clés qu'il ne modifie pas. Les
    #: réglages connus sont vérifiés ; les autres sont conservés tels quels.
    settings: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_settings(self) -> Self:
        if self.settings is None:
            return self
        for key in BOOLEAN_SETTINGS:
            if key in self.settings and not isinstance(self.settings[key], bool):
                raise ValueError(f"`{key}` doit valoir true ou false.")
        if DEFAULT_REORDER_POINT in self.settings:
            self.settings[DEFAULT_REORDER_POINT] = _checked_reorder_point(
                self.settings[DEFAULT_REORDER_POINT]
            )
        return self
