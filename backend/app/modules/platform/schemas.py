"""Schémas du module Platform.

Les réponses sur les entreprises sont des **listes blanches** : nom, slug, statut,
dates, nombre de comptes. Aucun montant, aucune donnée commerciale, même agrégée
(lots 24 et 26). Un test vérifie les clés exactes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CompanyStatus = Literal["trial", "active", "suspended"]
PlatformRole = Literal["administrator", "support"]


class PlatformLoginRequest(BaseModel):
    """Connexion de l'équipe : e-mail et mot de passe, aucune entreprise."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class PlatformTokenResponse(BaseModel):
    """Le refresh token part en cookie `httpOnly`, jamais dans le corps."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PlatformMe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    display_name: str
    role: PlatformRole


class CompanySummary(BaseModel):
    """Une ligne de la liste des entreprises."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    slug: str
    status: CompanyStatus
    created_at: datetime
    user_count: int
    #: Dernière ligne de son journal d'audit ; `None` : aucune encore.
    last_activity_at: datetime | None


class CompanyPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CompanySummary]
    page: int
    page_size: int
    total: int


class CompanyUser(BaseModel):
    """Un compte de l'entreprise : qui, quels rôles, dernière connexion."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    full_name: str
    roles: list[str]
    is_active: bool
    last_login_at: datetime | None


class CompanyDetail(CompanySummary):
    users: list[CompanyUser]


class CompanyStatusUpdate(BaseModel):
    """Suspendre ou réactiver. `trial` n'est jamais une cible ici (422)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "suspended"]
    reason: str = Field(min_length=3, max_length=500)
