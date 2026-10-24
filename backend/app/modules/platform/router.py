"""Routes HTTP de l'administration, toutes sous `/api/v1/platform` (ADR 0089).

Jeton à part (audience `coges-platform`), cookie de rafraîchissement à part, limité à
`/api/v1/platform/auth` : il ne part jamais vers les routes commerçantes, et le cookie
commerçant ne vient jamais ici. Derrière Caddy, ces routes ne répondent que sur le
sous-domaine de l'administration, filtré par adresse IP.
"""

from __future__ import annotations

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
    CompanyDetail,
    CompanyPage,
    CompanyStatusUpdate,
    PlanRead,
    PlatformLoginRequest,
    PlatformMe,
    PlatformTokenResponse,
    SubscriptionDetail,
    SubscriptionPaymentCreate,
    SubscriptionUpdate,
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
) -> CompanyPage:
    """Entreprises clientes : nom, slug, statut, comptes, dernière activité. Aucun montant."""
    return service.list_companies(platform.session, search=search, page=page, page_size=page_size)


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
