"""Schémas du module Platform.

Les réponses sur les entreprises sont des **listes blanches** : nom, slug, statut,
dates, nombre de comptes. Aucune donnée commerciale de l'entreprise, même agrégée
(lot 26). Les seuls montants sont ceux de l'abonnement que l'entreprise paie à CoGes
(ADR 0091). Un test vérifie les clés exactes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
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


# ---------------------------------------------------------- statistiques (ADR 0093)

StatsPeriod = Literal["current_month", "previous_month", "custom"]
StatsGranularity = Literal["month", "week"]


class CompanyStatusCounts(BaseModel):
    """Entreprises non supprimées, par statut d'accès ; `total` en est la somme."""

    model_config = ConfigDict(extra="forbid")

    trial: int
    active: int
    suspended: int
    total: int


class PlanBreakdown(BaseModel):
    """Une offre et ses entreprises, d'après l'**abonnement** : les essais (tous sur
    Premium) à part des payantes (`active` et `past_due`), pour ne pas gonfler l'offre."""

    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    trial: int
    paying: int
    suspended: int
    total: int


class StatsOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    computed_at: datetime
    companies: CompanyStatusCounts
    #: Comptes commerçants actifs et non supprimés, toutes entreprises vivantes confondues.
    active_users: int
    plans: list[PlanBreakdown]
    #: Entreprises sans abonnement (aucune attendue : l'essai naît avec l'entreprise).
    without_subscription: int


class RevenueRead(BaseModel):
    """Somme des paiements **déclarés reçus** sur la période, jamais un revenu théorique
    tiré des offres en cours. Jours de `start` à `end` compris, heure de Dakar."""

    model_config = ConfigDict(extra="forbid")

    period: StatsPeriod
    start: date
    end: date
    timezone: str
    total_fcfa: Amount
    payment_count: int
    computed_at: datetime


class SignupBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date
    count: int


class SignupsRead(BaseModel):
    """Nouvelles entreprises (non supprimées) sur 12 mois ou 52 semaines ; la dernière
    période est celle en cours, les périodes vides valent 0."""

    model_config = ConfigDict(extra="forbid")

    granularity: StatsGranularity
    timezone: str
    computed_at: datetime
    buckets: list[SignupBucket]
    total: int


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


# ------------------------------------------------------- équipe et accès (ADR 0094)

#: Politique de mot de passe de l'équipe, la même que la CLI (`create_platform_user`).
PLATFORM_PASSWORD_MIN = 12
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class TeamMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    display_name: str
    role: PlatformRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    #: Le compte qui regarde : l'écran ne lui propose ni suspension ni changement de profil.
    is_me: bool


class TeamInvitation(BaseModel):
    """Une invitation en attente : ni acceptée, ni révoquée, ni échue."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    display_name: str
    role: PlatformRole
    created_at: datetime
    expires_at: datetime
    invited_by_name: str


class TeamList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    members: list[TeamMember]
    invitations: list[TeamInvitation]


class TeamSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    computed_at: datetime
    members: int
    active: int
    suspended: int
    pending_invitations: int
    #: En attente et échues dans les 24 h.
    expiring_invitations: int


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254, pattern=_EMAIL_PATTERN)
    display_name: str = Field(min_length=1, max_length=120)
    role: PlatformRole

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("display_name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Le nom ne peut pas être vide.")
        return value.strip()


class InvitationIssued(BaseModel):
    """`invitation_url` n'est rendu qu'une fois, quand aucun e-mail ne peut partir."""

    model_config = ConfigDict(extra="forbid")

    invitation: TeamInvitation
    email_sent: bool
    invitation_url: str | None


class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=PLATFORM_PASSWORD_MIN, max_length=128)


class TeamMemberUpdate(BaseModel):
    """Changer le profil, suspendre ou réactiver. Une suspension exige sa raison."""

    model_config = ConfigDict(extra="forbid")

    role: PlatformRole | None = None
    is_active: bool | None = None
    reason: str | None = Field(default=None, min_length=3, max_length=500)

    @model_validator(mode="after")
    def _coherent(self) -> TeamMemberUpdate:
        if self.role is None and self.is_active is None:
            raise ValueError("Donnez un profil ou un statut.")
        if self.is_active is False and not (self.reason and self.reason.strip()):
            raise ValueError("Une suspension demande sa raison.")
        return self


MerchantUserStatus = Literal["active", "deactivated", "company_suspended"]
MerchantUserSort = Literal["name", "-name", "last_login", "-last_login"]


class MerchantUser(BaseModel):
    """Un compte commerçant, en lecture seule : colonnes accordées par 0026 seulement."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    full_name: str
    email: str | None
    company_id: UUID
    company_name: str
    roles: list[str]
    status: MerchantUserStatus
    last_login_at: datetime | None


class MerchantUserPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MerchantUser]
    page: int
    page_size: int
    total: int


AuditAction = Literal["login", "update", "insert", "cancel"]


class AuditEntry(BaseModel):
    """Une ligne du journal de la plateforme ; `diff` passe par une liste blanche."""

    model_config = ConfigDict(extra="forbid")

    id: int
    occurred_at: datetime
    actor_id: UUID | None
    actor_name: str | None
    action: AuditAction
    entity_table: str
    entity_id: UUID | None
    #: Le compte ou l'invité visé, quand la ligne parle de l'équipe.
    entity_name: str | None
    target_company_id: UUID | None
    target_company_name: str | None
    diff: dict[str, Any]


class AuditPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AuditEntry]
    page: int
    page_size: int
    total: int


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str


class ProfileRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: PlatformRole
    label: str
    description: str
    capabilities: list[Capability]


class TrialEnding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: UUID
    name: str
    trial_ends_at: datetime


class SuspendedCompany(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: UUID
    name: str


class ExpiringInvitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    display_name: str
    expires_at: datetime


class AttentionRead(BaseModel):
    """Ce qui demande une action, dès l'ouverture du tableau de bord."""

    model_config = ConfigDict(extra="forbid")

    computed_at: datetime
    #: Essais qui finissent dans les 7 jours.
    trials_ending: list[TrialEnding]
    #: Les 20 plus récentes ; `suspended_total` les compte toutes.
    suspended_companies: list[SuspendedCompany]
    suspended_total: int
    #: Invitations en attente qui échoient dans les 24 h.
    expiring_invitations: list[ExpiringInvitation]
