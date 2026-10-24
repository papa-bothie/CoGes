"""Schémas du module Platform.

Les réponses sur les entreprises sont des **listes blanches** : nom, slug, statut,
dates, nombre de comptes. Aucune donnée commerciale de l'entreprise, même agrégée
(lot 26). Les seuls montants sont ceux de l'abonnement que l'entreprise paie à CoGes
(ADR 0091). Un test vérifie les clés exactes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.money import Amount

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


# ------------------------------------------------------------ abonnements (ADR 0091)

SubscriptionStatus = Literal["trial", "active", "past_due", "suspended"]
#: Ce que l'équipe peut poser à la main : l'essai ne naît qu'avec l'entreprise.
SettableSubscriptionStatus = Literal["active", "past_due", "suspended"]
PaymentMethod = Literal["wave", "orange_money", "cash", "bank_transfer"]


class PlanRead(BaseModel):
    """Une offre. `max_users` à `None` : pas de plafond (palier « sur devis »)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    name: str
    price_fcfa: Amount | None
    max_users: int | None
    features: list[str]
    is_orderable: bool


class SubscriptionPaymentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    amount_fcfa: Amount
    paid_at: datetime
    method: PaymentMethod
    note: str | None
    recorded_at: datetime


class SubscriptionDetail(BaseModel):
    """L'abonnement d'une entreprise, ses comptes actifs et ses derniers paiements."""

    model_config = ConfigDict(extra="forbid")

    company_id: UUID
    plan: PlanRead
    status: SubscriptionStatus
    trial_ends_at: datetime | None
    started_at: datetime
    current_period_end: datetime | None
    active_users: int
    #: Les 50 plus récents ; `payments_total` les compte tous.
    payments: list[SubscriptionPaymentRead]
    payments_total: int


class SubscriptionUpdate(BaseModel):
    """Changer d'offre, de statut, ou les deux ; la raison va au journal."""

    model_config = ConfigDict(extra="forbid")

    plan_code: str | None = Field(default=None, min_length=1, max_length=40)
    status: SettableSubscriptionStatus | None = None
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def _something_changes(self) -> SubscriptionUpdate:
        if self.plan_code is None and self.status is None:
            raise ValueError("Donnez une offre ou un statut.")
        return self


class SubscriptionPaymentCreate(BaseModel):
    """Paiement reçu hors CoGes, déclaré par l'équipe. Montant en chaîne, jamais en float."""

    model_config = ConfigDict(extra="forbid")

    amount_fcfa: Amount

    @field_validator("amount_fcfa")
    @classmethod
    def _positive(cls, value: Decimal) -> Decimal:
        if value <= 0 or value >= Decimal("1e12"):
            raise ValueError("Le montant doit être positif.")
        return value

    paid_at: datetime
    method: PaymentMethod
    note: str | None = Field(default=None, max_length=500)

    @field_validator("paid_at")
    @classmethod
    def _aware_and_past(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("La date doit porter son fuseau.")
        if value > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("Un paiement ne peut pas être daté dans le futur.")
        return value


# ------------------------------------------------- accès support encadré (ADR 0092)

#: Durées proposées, en minutes : de 30 min à 4 h (la base vérifie aussi les 4 h).
SUPPORT_MIN_MINUTES = 30
SUPPORT_DEFAULT_MINUTES = 120
SUPPORT_MAX_MINUTES = 240


class SupportSessionCreate(BaseModel):
    """Bris de glace : le « pourquoi » est obligatoire, la durée bornée."""

    model_config = ConfigDict(extra="forbid")

    justification: str = Field(min_length=10, max_length=1000)
    duration_minutes: int = Field(
        default=SUPPORT_DEFAULT_MINUTES, ge=SUPPORT_MIN_MINUTES, le=SUPPORT_MAX_MINUTES
    )

    @field_validator("justification")
    @classmethod
    def _meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 10:
            raise ValueError("Expliquez en quelques mots pourquoi l'accès est nécessaire.")
        return cleaned


class SupportSessionRead(BaseModel):
    """Une session vue par l'équipe : qui l'a ouverte, pourquoi, quand."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    company_id: UUID
    opened_by: str
    opened_by_me: bool
    justification: str | None
    started_at: datetime
    expires_at: datetime
    ended_at: datetime | None
    is_open: bool


class SupportSessionList(BaseModel):
    """La session en cours (au plus une) et les dernières, ouverte comprise."""

    model_config = ConfigDict(extra="forbid")

    active: SupportSessionRead | None
    recent: list[SupportSessionRead]


class SupportAccessToken(BaseModel):
    """Le jeton de support : il ne vaut que pour cette session, en lecture seule."""

    model_config = ConfigDict(extra="forbid")

    session: SupportSessionRead
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
