"""Routes HTTP du module Signup (ADR 0118).

* publiques, sous `/auth/signup-requests` : 404 tant que `COGES_SIGNUP_ENABLED` est faux
  (seule `/auth/signup-config` répond toujours, pour que le front cache le bouton) ;
* de l'équipe, sous `/platform/signup-requests` : le jeton de l'administration, lecture
  pour l'administrateur et le support, décisions pour l'administrateur seul.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.config import get_settings
from app.core.deps import PlatformSession, client_ip, require_platform_role
from app.core.errors import NotFoundError
from app.modules.signup import service
from app.modules.signup.schemas import (
    SignupConfig,
    SignupEmail,
    SignupNeutral,
    SignupNote,
    SignupReject,
    SignupRequestAccepted,
    SignupRequestCreate,
    SignupRequestPage,
    SignupRequestRead,
    SignupStats,
    SignupVerified,
    SignupVerify,
)

MAX_PAGE_SIZE = 100


def require_signup_enabled() -> None:
    """Interrupteur éteint : la route n'existe pas (404), rien n'est lu ni écrit."""
    if not get_settings().signup_enabled:
        raise NotFoundError()


router = APIRouter(prefix="/auth", tags=["signup"])
public = APIRouter(
    prefix="/auth/signup-requests",
    tags=["signup"],
    dependencies=[Depends(require_signup_enabled)],
)
platform_router = APIRouter(prefix="/platform/signup-requests", tags=["platform-admin"])

Reader = Annotated[
    PlatformSession,
    Depends(require_platform_role("administrator", "support"), scope="function"),
]
Administrator = Annotated[
    PlatformSession, Depends(require_platform_role("administrator"), scope="function")
]


@router.get("/signup-config", response_model=SignupConfig)
def signup_config() -> SignupConfig:
    """Inscription ouverte ou non, et ce que l'écran doit dire. Aucun secret."""
    return service.config()


@public.post("", response_model=SignupRequestAccepted, status_code=status.HTTP_202_ACCEPTED)
def create_signup_request(payload: SignupRequestCreate, request: Request) -> SignupRequestAccepted:
    """« Créer ma boutique » : une demande, jamais une boutique. Réponse neutre."""
    return service.create_request(payload, ip_address=client_ip(request))


@public.post("/verify", response_model=SignupVerified)
def verify_signup_email(payload: SignupVerify, request: Request) -> SignupVerified:
    """Lien de l'e-mail : jeton à usage unique, puis activation de la boutique."""
    return service.verify(payload.token, ip_address=client_ip(request))


@public.post("/resend", response_model=SignupNeutral, status_code=status.HTTP_202_ACCEPTED)
def resend_signup_email(payload: SignupEmail) -> SignupNeutral:
    """« Renvoyer le lien » : un envoi par minute, cinq par jour. Réponse neutre."""
    return service.resend(str(payload.email))


@public.post("/contact-team", response_model=SignupNeutral, status_code=status.HTTP_202_ACCEPTED)
def contact_signup_team(payload: SignupEmail) -> SignupNeutral:
    """« Je n'ai pas reçu l'e-mail » : la demande passe dans la file de l'équipe."""
    return service.contact_team(str(payload.email))


@platform_router.get("", response_model=SignupRequestPage)
def list_signup_requests(
    platform: Reader,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    status_filter: Annotated[
        Literal["pending", "activated", "rejected", "abandoned"] | None, Query(alias="status")
    ] = None,
    path: Literal["email", "team"] | None = None,
    older_than_hours: Annotated[int | None, Query(ge=1, le=24 * 366)] = None,
) -> SignupRequestPage:
    """Demandes d'inscription, les plus récentes d'abord, avec le compteur de la file."""
    return service.list_requests(
        platform.session,
        status=status_filter,
        path=path,
        older_than_hours=older_than_hours,
        page=page,
        page_size=page_size,
    )


@platform_router.get("/stats", response_model=SignupStats)
def signup_stats(platform: Reader, days: Annotated[int, Query(ge=1, le=366)] = 30) -> SignupStats:
    """Reçues, activées par lien ou par l'équipe, refusées, abandonnées, délai moyen."""
    return service.stats(platform.session, days=days)


@platform_router.get("/{request_id}", response_model=SignupRequestRead)
def get_signup_request(request_id: UUID, platform: Reader) -> SignupRequestRead:
    """Une demande, avec « déjà connu : boutique X » si le numéro ou l'e-mail l'est."""
    return service.get_request(platform.session, request_id)


@platform_router.post("/{request_id}/activate", response_model=SignupRequestRead)
def activate_signup_request(
    request_id: UUID, request: Request, platform: Administrator
) -> SignupRequestRead:
    """Ouvre la boutique : la même activation que le lien e-mail, en une transaction."""
    service.activate_request(
        request_id,
        actor=platform.admin.platform_user_id,
        via="team",
        ip_address=client_ip(request),
    )
    return service.get_request(platform.session, request_id)


@platform_router.post("/{request_id}/reject", response_model=SignupRequestRead)
def reject_signup_request(
    request_id: UUID, payload: SignupReject, request: Request, platform: Administrator
) -> SignupRequestRead:
    """Refuse la demande : raison en liste fermée, note facultative, audit critique."""
    return service.reject(
        platform.session,
        request_id,
        actor=platform.admin.platform_user_id,
        reason=payload.reason,
        note=payload.note,
        ip_address=client_ip(request),
    )


@platform_router.put("/{request_id}/note", response_model=SignupRequestRead)
def note_signup_request(
    request_id: UUID, payload: SignupNote, request: Request, platform: Administrator
) -> SignupRequestRead:
    """Note de l'équipe (« appelé lundi, rappeler jeudi ») ; le fait est audité."""
    return service.set_note(
        platform.session,
        request_id,
        actor=platform.admin.platform_user_id,
        note=payload.note,
        ip_address=client_ip(request),
    )
