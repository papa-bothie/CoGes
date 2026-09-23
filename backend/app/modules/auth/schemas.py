"""Schémas du module Auth."""

from __future__ import annotations

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
