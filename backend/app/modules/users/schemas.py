"""Schémas du module Users."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.phone import normalise_phone


class UserRoleRead(BaseModel):
    """Rôle porté par un compte. `description` est le libellé affiché (ADR 0007)."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    name: str
    description: str | None
    is_system: bool


class UserRead(BaseModel):
    """Vue publique d'un utilisateur. Le hachage du mot de passe n'en fait jamais partie."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    email: str | None
    #: Chiffres seuls (« 770000000 ») ; le front les groupe à l'affichage.
    phone: str | None
    full_name: str
    is_active: bool
    #: Vrai tant que le mot de passe provisoire n'a pas été remplacé (ADR 0074).
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime
    #: Rôles du compte (ADR 0053) : l'écran Utilisateurs les affiche sans N+1.
    roles: list[UserRoleRead] = Field(default_factory=list)


class UserCreate(BaseModel):
    """Un compte se crée avec un e-mail, un téléphone, ou les deux (ADR 0074).

    Sans mot de passe, le serveur en tire un provisoire lisible, le rend **une seule
    fois** dans la réponse et oblige à le changer à la première connexion.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    full_name: str = Field(min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=12, max_length=128)
    role_ids: list[UUID] = Field(default_factory=list)

    @field_validator("phone")
    @classmethod
    def _phone_digits(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        digits = normalise_phone(value)
        if digits is None:
            raise ValueError("Ce numéro de téléphone n'est pas valide.")
        return digits

    @model_validator(mode="after")
    def _contact(self) -> Self:
        if self.email is None and self.phone is None:
            raise ValueError("Donnez un e-mail ou un numéro de téléphone.")
        return self


class UserCreated(UserRead):
    """Le compte créé, et son mot de passe provisoire s'il a été tiré par le serveur.

    C'est la seule fois où ce mot de passe sort : il n'est stocké que haché.
    """

    temporary_password: str | None = None


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=12, max_length=128)


class UserPage(BaseModel):
    """Page de résultats. La pagination est obligatoire sur toutes les listes."""

    model_config = ConfigDict(extra="forbid")

    items: list[UserRead]
    page: int
    page_size: int
    total: int
