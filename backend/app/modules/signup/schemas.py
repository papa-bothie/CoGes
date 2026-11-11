"""Schémas du module Signup (ADR 0118)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.phone import to_e164

SignupPath = Literal["email", "team"]
SignupStatus = Literal["pending", "activated", "rejected", "abandoned"]
#: Raisons d'un refus, en liste fermée (la note dit le reste).
RejectReason = Literal["unreachable", "duplicate", "not_a_business", "fraud", "other"]


def _stripped(value: str) -> str:
    return " ".join(value.split())


class SignupRequestCreate(BaseModel):
    """Formulaire public « Créer ma boutique ». Le numéro est obligatoire, l'e-mail non."""

    model_config = ConfigDict(extra="forbid")

    shop_name: str = Field(min_length=2, max_length=80)
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=30)
    email: EmailStr | None = None
    #: Même politique que les comptes (`PasswordUpdate`) : 12 caractères au moins.
    password: str = Field(min_length=12, max_length=128)
    #: La case des conditions ; la version enregistrée est celle du serveur.
    accept_legal: Literal[True]
    #: Champ piège, invisible à l'écran : rempli, la demande est ignorée sans le dire.
    website: str = Field(default="", max_length=200)

    @field_validator("shop_name", "full_name")
    @classmethod
    def _names(cls, value: str) -> str:
        cleaned = _stripped(value)
        if len(cleaned) < 2:
            raise ValueError("Deux caractères au moins.")
        return cleaned

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        e164 = to_e164(value)
        if e164 is None:
            raise ValueError("Ce numéro de téléphone n'est pas valide.")
        return e164

    @field_validator("email", mode="before")
    @classmethod
    def _empty_email(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip().lower()
            return value or None
        return value


class SignupRequestAccepted(BaseModel):
    """Réponse neutre : la même pour un même chemin, que le numéro ou l'e-mail soient
    nouveaux, déjà en attente ou déjà liés à un compte (aucune énumération)."""

    model_config = ConfigDict(extra="forbid")

    path: SignupPath
    message: str


class SignupVerify(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)


class SignupVerified(BaseModel):
    """`ready` : la boutique est ouverte, `company_slug` sert à préremplir la connexion.
    `team` : l'adresse est vérifiée, mais l'équipe doit voir la demande avant."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "team"]
    company_slug: str | None = None
    message: str


class SignupEmail(BaseModel):
    """Renvoyer le lien, ou passer par l'équipe : réponse neutre dans les deux cas."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def _lower(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class SignupNeutral(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str


class SignupConfig(BaseModel):
    """Réglages publics, sans secret : le front affiche ou cache « Créer ma boutique »."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    #: Vrai si un e-mail ouvre la boutique tout de suite (SMTP configuré).
    instant_with_email: bool
    support_whatsapp: str
    resend_interval_seconds: int


# --- Administration (routes /api/v1/platform/signup-requests) ---------------------------


class KnownAccount(BaseModel):
    """Une boutique où ce numéro ou cet e-mail ont déjà un compte."""

    model_config = ConfigDict(extra="forbid")

    company_id: UUID
    company_name: str
    company_slug: str
    matched_on: Literal["phone", "email"]


class SignupRequestRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    shop_name: str | None
    full_name: str | None
    phone: str | None
    email: str | None
    path: SignupPath
    status: SignupStatus
    email_verified_at: datetime | None
    reject_reason: RejectReason | None
    team_note: str | None
    created_at: datetime
    path_changed_at: datetime | None
    decided_at: datetime | None
    decided_via: Literal["email_link", "team", "system"] | None
    company_id: UUID | None
    company_slug: str | None = None
    legal_version: str
    purged: bool
    known_accounts: list[KnownAccount] = Field(default_factory=list)


class SignupRequestPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SignupRequestRead]
    total: int
    page: int
    page_size: int
    #: Demandes qui attendent l'équipe : le compteur du menu « Demandes ».
    team_queue: int
    smtp_configured: bool


class SignupReject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: RejectReason
    note: str | None = Field(default=None, max_length=1000)


class SignupNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=1000)


class SignupStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received_email: int
    received_team: int
    activated_by_link: int
    activated_by_team: int
    rejected: int
    abandoned: int
    pending_team: int
    pending_email: int
    #: Délai moyen entre la demande et l'activation, en heures ; `None` sans activation.
    average_hours_to_activation: float | None
    smtp_configured: bool
