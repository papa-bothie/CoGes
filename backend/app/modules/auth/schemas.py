"""Schémas du module Auth."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LoginRequest(BaseModel):
    """L'identifiant de connexion est le **couple** (slug d'entreprise, e-mail ou
    téléphone) (ADR 0074).

    Un e-mail ou un numéro seul serait ambigu : il est unique par entreprise, pas
    globalement (§ 2.2). C'est ce couple qui rend le `company_id` du jeton
    déterministe. `email` reste accepté pour les clients d'avant le lot 3e.
    """

    model_config = ConfigDict(extra="forbid")

    company_slug: str = Field(min_length=3, max_length=40, pattern="^[a-z0-9-]{3,40}$")
    identifier: str | None = Field(default=None, min_length=1, max_length=254)
    email: str | None = Field(default=None, min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _one_identifier(self) -> Self:
        if (self.identifier or self.email) is None:
            raise ValueError("Donnez votre e-mail ou votre numéro de téléphone.")
        return self

    @property
    def login_identifier(self) -> str:
        return (self.identifier or self.email or "").strip()


class PasswordUpdate(BaseModel):
    """Le titulaire remplace son mot de passe (écran « Choisissez votre mot de passe »)."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class TokenResponse(BaseModel):
    """Le refresh token n'apparaît pas ici : il part en cookie `httpOnly`."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str | None
    phone: str | None
    full_name: str
    #: Vrai : le front ouvre « Choisissez votre mot de passe » avant tout (ADR 0074).
    must_change_password: bool


class MeRole(BaseModel):
    """`name` est le nom technique stable, `description` le libellé affiché."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str | None
    is_system: bool


class MeCompany(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    slug: str
    currency: str
    timezone: str
    tax_enabled: bool
    #: Reçu ouvert par défaut après une vente (écran 24, ADR 0075).
    receipt_format: Literal["ticket", "a4"]


class MeResponse(BaseModel):
    """Identité de la session : ce dont l'interface a besoin pour s'afficher.

    Les permissions ne servent au front qu'à **masquer** : chaque route les vérifie
    à nouveau côté serveur. Aucune permission n'est exigée pour lire sa propre
    identité, sans quoi un vendeur (ni `users:read`, ni `company:read`) ne saurait
    pas qui il est.
    """

    model_config = ConfigDict(extra="forbid")

    user: MeUser
    roles: list[MeRole]
    permissions: list[str]
    company: MeCompany
