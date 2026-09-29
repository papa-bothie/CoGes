"""Schémas du module Auth."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    """L'identifiant de connexion est le **couple** (slug d'entreprise, e-mail).

    Un e-mail seul serait ambigu : il est unique par entreprise, pas globalement
    (§ 2.2). C'est ce couple qui rend le `company_id` du jeton déterministe.
    """

    model_config = ConfigDict(extra="forbid")

    company_slug: str = Field(min_length=3, max_length=40, pattern="^[a-z0-9-]{3,40}$")
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Le refresh token n'apparaît pas ici : il part en cookie `httpOnly`."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    full_name: str


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
