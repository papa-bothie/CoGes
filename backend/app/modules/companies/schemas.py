"""Schémas du module Companies."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Réglages booléens connus ; absents, ils valent « activé » (ADR 0022, 0036).
BOOLEAN_SETTINGS = ("tax_enabled", "intelligence_enabled")
#: Seuil d'alerte appliqué à un produit suivi créé sans seuil (ADR 0054).
DEFAULT_REORDER_POINT = "default_reorder_point"
#: Même borne que `products.reorder_point` : `numeric(14,3)`.
_MAX_REORDER = Decimal("99999999999.999")
#: Taux de TVA appliqué à un article créé sans taux (ADR 0066, complément).
DEFAULT_TAX_RATE = "default_tax_rate"


def _checked_tax_rate(value: Any) -> str | None:
    if value is None:
        return None
    # Chaîne décimale seulement, comme `products.default_tax_rate` (`numeric(6,4)`).
    if not isinstance(value, str):
        raise ValueError('Le taux par défaut s\'envoie en chaîne décimale, par exemple "0.18".')
    try:
        rate = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Taux par défaut illisible.") from exc
    exponent = rate.as_tuple().exponent
    if (
        not rate.is_finite()
        or rate < 0
        or rate >= 1
        or (isinstance(exponent, int) and exponent < -4)
    ):
        raise ValueError("Taux par défaut : de 0 à moins de 1, quatre décimales au plus.")
    return str(rate)


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


#: Coordonnées de la boutique (révision 0016) → longueur maximale, comme en base.
SHOP_FIELDS: dict[str, int] = {
    "address": 200,
    "phone": 30,
    "wave_number": 30,
    "ninea": 30,
    "rc": 40,
    "receipt_footer": 300,
}


class CompanyRead(BaseModel):
    """Vue publique de l'entreprise courante."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    name: str
    slug: str
    currency: str
    timezone: str
    settings: dict[str, Any]
    address: str | None
    phone: str | None
    wave_number: str | None
    ninea: str | None
    rc: str | None
    receipt_footer: str | None
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
    #: Coordonnées imprimées sur le reçu. `null` ou une chaîne vide les efface.
    address: str | None = Field(default=None, max_length=SHOP_FIELDS["address"])
    phone: str | None = Field(default=None, max_length=SHOP_FIELDS["phone"])
    wave_number: str | None = Field(default=None, max_length=SHOP_FIELDS["wave_number"])
    ninea: str | None = Field(default=None, max_length=SHOP_FIELDS["ninea"])
    rc: str | None = Field(default=None, max_length=SHOP_FIELDS["rc"])
    receipt_footer: str | None = Field(default=None, max_length=SHOP_FIELDS["receipt_footer"])

    @field_validator(*SHOP_FIELDS, mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        # Une ligne vide ne s'imprime pas : elle s'enregistre comme absente.
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def _check_settings(self) -> Self:
        if self.settings is None:
            return self
        for key in BOOLEAN_SETTINGS:
            if key in self.settings and not isinstance(self.settings[key], bool):
                raise ValueError(f"`{key}` doit valoir true ou false.")
        if DEFAULT_TAX_RATE in self.settings:
            self.settings[DEFAULT_TAX_RATE] = _checked_tax_rate(self.settings[DEFAULT_TAX_RATE])
        if DEFAULT_REORDER_POINT in self.settings:
            self.settings[DEFAULT_REORDER_POINT] = _checked_reorder_point(
                self.settings[DEFAULT_REORDER_POINT]
            )
        return self
