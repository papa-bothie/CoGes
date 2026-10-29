"""Routes HTTP de l'administration, toutes sous `/api/v1/platform` (ADR 0089).

Jeton à part (audience `coges-platform`), cookie de rafraîchissement à part, limité à
`/api/v1/platform/auth` : il ne part jamais vers les routes commerçantes, et le cookie
commerçant ne vient jamais ici. Derrière Caddy, ces routes ne répondent que sur le
sous-domaine de l'administration, derrière Cloudflare Access (ADR 0104, jeton vérifié par
`CloudflareAccessMiddleware` avant toute route) ou, en retour arrière, une liste d'adresses.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.core.config import get_settings
from app.core.deps import (
    CurrentPlatformAdmin,
    PlatformSession,
    client_ip,
    require_platform_role,
)
from app.core.errors import AuthenticationRequiredError
from app.core.idempotency import (
    IDEMPOTENCY_HEADER,
    MAX_KEY_LENGTH,
    MIN_KEY_LENGTH,
    REPLAY_HEADER,
    IdempotencyKeyMalformedError,
    IdempotencyKeyRequiredError,
)
from app.core.repository import MAX_PAGE_SIZE
from app.modules.platform import service
from app.modules.platform.schemas import (
    AttentionRead,
    AuditAction,
    AuditPage,
    CompanyDetail,
    CompanyPage,
    CompanyStatus,
    CompanyStatusUpdate,
    InvitationAccept,
    InvitationCreate,
    InvitationIssued,
    MerchantUserPage,
    MerchantUserSort,
    MerchantUserStatus,
    PlanRead,
    PlatformLoginRequest,
    PlatformMe,
    PlatformTokenResponse,
    ProfileRead,
    RevenueRead,
    SignupsRead,
    StatsGranularity,
    StatsOverview,
    StatsPeriod,
    SubscriptionDetail,
    SubscriptionPaymentCreate,
    SubscriptionUpdate,
    SupportAccessToken,
    SupportSessionCreate,
    SupportSessionList,
    TeamList,
    TeamMember,
    TeamMemberUpdate,
    TeamSummary,
)

router = APIRouter(prefix="/platform", tags=["platform-admin"])

REFRESH_COOKIE_NAME = "coges_platform_refresh"
REFRESH_COOKIE_PATH = "/api/v1/platform/auth"

Administrator = Annotated[
    PlatformSession, Depends(require_platform_role("administrator"), scope="function")
]


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=settings.jwt_refresh_ttl_seconds,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.env != "local",
        # `Strict` : l'administration n'est jamais atteinte par un lien venu d'ailleurs.
        samesite="strict",
    )


@router.get("/access", status_code=status.HTTP_204_NO_CONTENT)
def access() -> None:
    """Contrôle demandé par Caddy avant de servir une page de l'administration (ADR 0104).

    Le travail est fait avant la route, par `CloudflareAccessMiddleware` : 204 si le jeton
    Cloudflare Access est valide, 403 sinon. Aucun compte, aucune donnée.
    """


@router.post("/auth/login", response_model=PlatformTokenResponse)
def login(
    payload: PlatformLoginRequest, request: Request, response: Response
) -> PlatformTokenResponse:
    """Connexion de l'équipe CoGes : e-mail et mot de passe, aucune entreprise."""
    tokens = service.login(
        payload.email,
        payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )
    _set_refresh_cookie(response, tokens.refresh_token)
    return PlatformTokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/auth/refresh", response_model=PlatformTokenResponse)
def refresh(request: Request, response: Response) -> PlatformTokenResponse:
    """Rotation du refresh token de l'administration."""
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise AuthenticationRequiredError("Jeton de rafraîchissement absent.")
    tokens = service.refresh(
        raw_token, user_agent=request.headers.get("user-agent"), ip_address=client_ip(request)
    )
    _set_refresh_cookie(response, tokens.refresh_token)
    return PlatformTokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_token:
        service.logout(raw_token)
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


@router.get("/auth/me", response_model=PlatformMe)
def me(platform: CurrentPlatformAdmin) -> PlatformMe:
    return service.me(platform.session, platform.admin)


@router.get("/companies", response_model=CompanyPage)
def list_companies(
    platform: CurrentPlatformAdmin,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    search: Annotated[str | None, Query(max_length=100)] = None,
    status: CompanyStatus | None = None,
) -> CompanyPage:
    """Entreprises clientes : nom, slug, statut, comptes, dernière activité. Aucun montant."""
    return service.list_companies(
        platform.session, search=search, page=page, page_size=page_size, status=status
    )


@router.get("/companies/{company_id}", response_model=CompanyDetail)
def get_company(company_id: UUID, platform: CurrentPlatformAdmin) -> CompanyDetail:
    return service.get_company(platform.session, company_id)


@router.patch("/companies/{company_id}/status", response_model=CompanyDetail)
def set_company_status(
    company_id: UUID, payload: CompanyStatusUpdate, request: Request, platform: Administrator
) -> CompanyDetail:
    """Suspendre ou réactiver (profil `administrator`). Audit critique, gérant prévenu."""
    return service.set_company_status(
        platform.session,
        platform.admin,
        company_id,
        status=payload.status,
        reason=payload.reason.strip(),
        ip_address=client_ip(request),
    )


# ------------------------------------------------------------ abonnements (ADR 0091)


@router.get("/plans", response_model=list[PlanRead])
def list_plans(platform: CurrentPlatformAdmin) -> list[PlanRead]:
    """Les offres, vendables ou non (palier « sur devis »). Quelques lignes : pas de page."""
    return service.list_plans(platform.session)


@router.get("/companies/{company_id}/subscription", response_model=SubscriptionDetail)
def get_subscription(company_id: UUID, platform: CurrentPlatformAdmin) -> SubscriptionDetail:
    """Offre, statut, dates, comptes actifs et 50 derniers paiements déclarés."""
    return service.get_subscription(platform.session, company_id)


@router.patch("/companies/{company_id}/subscription", response_model=SubscriptionDetail)
def change_subscription(
    company_id: UUID, payload: SubscriptionUpdate, request: Request, platform: Administrator
) -> SubscriptionDetail:
    """Changer d'offre ou de statut (profil `administrator`). Audit critique.

    Une offre trop petite pour les comptes actifs : 409 `plan_downgrade_too_many_users`,
    avec le nombre de comptes à désactiver d'abord.
    """
    return service.change_subscription(
        platform.session, platform.admin, company_id, payload, ip_address=client_ip(request)
    )


@router.post(
    "/companies/{company_id}/payments",
    response_model=SubscriptionDetail,
    status_code=status.HTTP_201_CREATED,
)
def record_payment(
    company_id: UUID,
    payload: SubscriptionPaymentCreate,
    request: Request,
    response: Response,
    platform: Administrator,
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> SubscriptionDetail:
    """Paiement reçu hors CoGes (profil `administrator`), `Idempotency-Key` obligatoire.

    L'abonnement devient actif et avance d'un mois ; une entreprise suspendue retrouve
    l'accès. La même clé rejouée rend l'abonnement en 200, sans second paiement.
    """
    if idempotency_key is None:
        raise IdempotencyKeyRequiredError()
    key = idempotency_key.strip()
    if not MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH:
        raise IdempotencyKeyMalformedError()
    detail, replayed = service.record_payment(
        platform.session,
        platform.admin,
        company_id,
        payload,
        idempotency_key=key,
        ip_address=client_ip(request),
    )
    if replayed:
        response.status_code = status.HTTP_200_OK
        response.headers[REPLAY_HEADER] = "true"
    return detail


# ---------------------------------------------------------- statistiques (ADR 0093)


@router.get("/stats/overview", response_model=StatsOverview)
def stats_overview(platform: CurrentPlatformAdmin) -> StatsOverview:
    """Entreprises par statut et par offre (essais à part), comptes actifs."""
    return service.stats_overview(platform.session)


@router.get("/stats/revenue", response_model=RevenueRead)
def stats_revenue(
    platform: CurrentPlatformAdmin,
    period: StatsPeriod = "current_month",
    start: date | None = None,
    end: date | None = None,
) -> RevenueRead:
    """Somme des paiements **déclarés reçus** sur la période (heure de Dakar, bornes
    comprises) ; `custom` : `start` et `end`, 366 jours au plus, jamais après aujourd'hui."""
    return service.stats_revenue(platform.session, period, start, end)


@router.get("/stats/signups", response_model=SignupsRead)
def stats_signups(
    platform: CurrentPlatformAdmin, granularity: StatsGranularity = "month"
) -> SignupsRead:
    """Nouvelles entreprises par mois (12) ou par semaine (52), périodes vides à 0."""
    return service.stats_signups(platform.session, granularity)


# ------------------------------------------------- accès support encadré (ADR 0092)


@router.get("/companies/{company_id}/support-sessions", response_model=SupportSessionList)
def list_support_sessions(company_id: UUID, platform: CurrentPlatformAdmin) -> SupportSessionList:
    """La session en cours (au plus une) et les 20 dernières, avec qui et pourquoi."""
    return service.list_support_sessions(platform.session, platform.admin, company_id)


@router.post(
    "/companies/{company_id}/support-sessions",
    response_model=SupportAccessToken,
    status_code=status.HTTP_201_CREATED,
)
def open_support_session(
    company_id: UUID,
    payload: SupportSessionCreate,
    request: Request,
    platform: CurrentPlatformAdmin,
) -> SupportAccessToken:
    """Bris de glace (administrateur et support) : justification obligatoire, 2 h par
    défaut, 4 h au plus. Écrit dans le journal de l'administration **et** dans celui de
    l'entreprise ; le gérant est prévenu par e-mail et dans la cloche. Le jeton rendu
    lit l'entreprise comme un utilisateur, en lecture seule."""
    return service.open_support_session(
        platform.session, platform.admin, company_id, payload, ip_address=client_ip(request)
    )


@router.post("/support-sessions/{session_id}/token", response_model=SupportAccessToken)
def issue_support_token(
    session_id: UUID, request: Request, platform: CurrentPlatformAdmin
) -> SupportAccessToken:
    """Redonne le jeton d'une session ouverte, à qui l'a ouverte seulement. Audité."""
    return service.issue_support_token(
        platform.session, platform.admin, session_id, ip_address=client_ip(request)
    )


@router.delete("/support-sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def close_support_session(
    session_id: UUID, request: Request, platform: CurrentPlatformAdmin
) -> None:
    """Ferme l'accès avant l'heure ; le jeton cesse de servir à la requête suivante.
    Écrit dans les deux journaux."""
    service.close_support_session(
        platform.session, platform.admin, session_id, ip_address=client_ip(request)
    )


# ------------------------------------------------------- équipe et accès (ADR 0094)


@router.post("/auth/accept-invitation", response_model=PlatformTokenResponse)
def accept_invitation(
    payload: InvitationAccept, request: Request, response: Response
) -> PlatformTokenResponse:
    """Publique : le collègue invité choisit son mot de passe. Compte créé, jeton consommé,
    session ouverte. Même réponse pour tout lien qui n'est plus valable ; freinée par
    adresse IP comme la connexion."""
    tokens = service.accept_invitation(
        payload.token,
        payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )
    _set_refresh_cookie(response, tokens.refresh_token)
    return PlatformTokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.get("/team", response_model=TeamList)
def list_team(platform: CurrentPlatformAdmin) -> TeamList:
    """Les comptes de l'équipe et les invitations en attente."""
    return service.list_team(platform.session, platform.admin)


@router.get("/team/summary", response_model=TeamSummary)
def team_summary(platform: CurrentPlatformAdmin) -> TeamSummary:
    return service.team_summary(platform.session)


@router.post(
    "/team/invitations", response_model=InvitationIssued, status_code=status.HTTP_201_CREATED
)
def invite(
    payload: InvitationCreate,
    request: Request,
    response: Response,
    platform: Administrator,
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> InvitationIssued:
    """Inviter un collègue (profil `administrator`), `Idempotency-Key` obligatoire : un
    double clic n'envoie pas deux e-mails. Sans SMTP, le lien est rendu une fois."""
    if idempotency_key is None:
        raise IdempotencyKeyRequiredError()
    key = idempotency_key.strip()
    if not MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH:
        raise IdempotencyKeyMalformedError()
    issued, replayed = service.invite(
        platform.session,
        platform.admin,
        payload,
        idempotency_key=key,
        ip_address=client_ip(request),
    )
    if replayed:
        response.status_code = status.HTTP_200_OK
        response.headers[REPLAY_HEADER] = "true"
    return issued


@router.post("/team/invitations/{invitation_id}/resend", response_model=InvitationIssued)
def resend_invitation(
    invitation_id: UUID, request: Request, platform: Administrator
) -> InvitationIssued:
    """Nouveau lien valable 72 h ; l'ancien ne sert plus."""
    return service.resend_invitation(
        platform.session, platform.admin, invitation_id, ip_address=client_ip(request)
    )


@router.delete("/team/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(invitation_id: UUID, request: Request, platform: Administrator) -> None:
    service.revoke_invitation(
        platform.session, platform.admin, invitation_id, ip_address=client_ip(request)
    )


@router.patch("/team/{user_id}", response_model=TeamMember)
def update_member(
    user_id: UUID, payload: TeamMemberUpdate, request: Request, platform: Administrator
) -> TeamMember:
    """Changer le profil d'un collègue, le suspendre (raison obligatoire) ou le réactiver.
    Jamais son propre compte (409 `cannot_modify_self`) ; il reste toujours un
    administrateur actif (409 `last_administrator`)."""
    return service.update_member(
        platform.session, platform.admin, user_id, payload, ip_address=client_ip(request)
    )


@router.get("/users", response_model=MerchantUserPage)
def list_merchant_users(
    platform: CurrentPlatformAdmin,
    q: Annotated[str | None, Query(max_length=100)] = None,
    role: Annotated[str | None, Query(max_length=60)] = None,
    status: MerchantUserStatus | None = None,
    company_id: UUID | None = None,
    sort: MerchantUserSort = "-last_login",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> MerchantUserPage:
    """Comptes des commerçants, toutes entreprises, **en lecture seule** : leur gérant les
    gère. Nom, e-mail, entreprise, rôles, statut, dernière connexion."""
    return service.list_merchant_users(
        platform.session,
        search=q,
        role=role,
        status=status,
        company_id=company_id,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.get("/audit", response_model=AuditPage)
def list_audit(
    platform: Administrator,
    actor_id: UUID | None = None,
    action: AuditAction | None = None,
    company_id: UUID | None = None,
    entity_id: UUID | None = None,
    start: date | None = None,
    end: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
) -> AuditPage:
    """Journal des modifications de la plateforme (profil `administrator`), le plus récent
    d'abord ; jours de `start` à `end` compris, heure de Dakar. Aucun secret dans `diff`."""
    return service.list_audit(
        platform.session,
        actor_id=actor_id,
        action=action,
        company_id=company_id,
        entity_id=entity_id,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )


@router.get("/roles", response_model=list[ProfileRead])
def list_profiles(request: Request, platform: CurrentPlatformAdmin) -> list[ProfileRead]:
    """Les deux profils et ce que chacun peut faire, déduit des routes elles-mêmes."""
    return service.profiles(request.app.routes)


@router.get("/attention", response_model=AttentionRead)
def attention(platform: CurrentPlatformAdmin) -> AttentionRead:
    """Essais qui finissent sous 7 jours, entreprises suspendues, invitations qui échoient
    sous 24 h."""
    return service.attention(platform.session)
