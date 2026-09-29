"""Routes HTTP du module Auth.

Transport des jetons (ADR 0006) : l'**access token** est renvoyé dans le corps et
vit en mémoire côté navigateur ; le **refresh token** part dans un cookie
`httpOnly; Secure; SameSite=Lax`, donc hors de portée d'un script. `SameSite=Lax`
empêche l'envoi du cookie sur une requête POST venue d'un autre site, ce qui couvre
le risque CSRF sur `/auth/refresh`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.core.config import get_settings
from app.core.deps import CurrentTenant, client_ip
from app.core.errors import AuthenticationRequiredError
from app.modules.auth import service
from app.modules.auth.schemas import LoginRequest, MeResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "coges_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=settings.jwt_refresh_ttl_seconds,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        # En local (HTTP), `Secure` empêcherait l'envoi du cookie.
        secure=settings.env != "local",
        samesite="lax",
    )


def _read_refresh_cookie(request: Request) -> str:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise AuthenticationRequiredError("Jeton de rafraîchissement absent.")
    return raw_token


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> TokenResponse:
    """Connexion par (slug d'entreprise, e-mail, mot de passe)."""
    tokens = service.login(
        payload,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )
    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response) -> TokenResponse:
    """Rotation du refresh token. Un jeton rejoué révoque toute sa famille."""
    tokens = service.refresh(
        _read_refresh_cookie(request),
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )
    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    """Révoque la famille de sessions et efface le cookie."""
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_token:
        service.logout(raw_token)
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


@router.get("/me", response_model=MeResponse)
def me(tenant: CurrentTenant) -> MeResponse:
    """Utilisateur connecté, rôles, permissions et entreprise.

    Authentifié, sans permission requise : le front en tire l'en-tête et masque les
    actions interdites. Le serveur reste seul juge à chaque appel.
    """
    return service.current_identity(tenant.session, tenant.ctx)
