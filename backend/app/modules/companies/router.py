"""Routes HTTP du module Companies. Aucune requête SQL ici."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status

from app.core.deps import CurrentTenant, TenantSession, client_ip, require_permission
from app.modules.companies import service
from app.modules.companies.schemas import (
    CompanyLogoRead,
    CompanyRead,
    CompanyUpdate,
    SupportAccessRead,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/me", response_model=CompanyRead)
def read_current_company(
    tenant: Annotated[TenantSession, Depends(require_permission("company:read"))],
) -> CompanyRead:
    """Paramètres de l'entreprise de l'utilisateur connecté."""
    company = service.get_current_company(tenant.session, tenant.ctx)
    return service.describe(tenant.session, tenant.ctx, company)


@router.patch("/me", response_model=CompanyRead)
def update_current_company(
    payload: CompanyUpdate,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("company:update"))],
) -> CompanyRead:
    """Modifie les paramètres. Toute modification sensible est auditée."""
    company = service.update_current_company(
        tenant.session, tenant.ctx, payload, ip_address=client_ip(request)
    )
    return service.describe(tenant.session, tenant.ctx, company)


@router.get("/me/support-access", response_model=SupportAccessRead)
def read_support_access(tenant: CurrentTenant) -> SupportAccessRead:
    """Accès support en cours (ADR 0092) : début et fin, jamais qui.

    Sans permission : **tout** utilisateur de l'entreprise doit voir le bandeau.
    """
    return service.support_access(tenant.session, tenant.ctx)


@router.get(
    "/me/logo",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "Le logo, en PNG"}},
)
def read_logo(tenant: CurrentTenant) -> Response:
    """Le logo de la boutique (ADR 0111), ou 404 `logo_not_found`.

    Sans permission : tout utilisateur de l'entreprise imprime des reçus qui le portent.
    Jamais gardé : ni par le navigateur, ni par un intermédiaire.
    """
    png = service.get_logo_png(tenant.session, tenant.ctx)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.put("/me/logo", response_model=CompanyLogoRead)
def put_logo(
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("company:update"))],
    file: Annotated[UploadFile, File(description="PNG, JPEG ou WebP, 2 Mo au plus")],
) -> CompanyLogoRead:
    """Ajoute ou change le logo. L'image est vérifiée, ré-encodée en PNG et réduite."""
    content = file.file.read()
    return service.set_logo(tenant.session, tenant.ctx, content, ip_address=client_ip(request))


@router.delete("/me/logo", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_logo(
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("company:update"))],
) -> Response:
    """Retire le logo. 404 `logo_not_found` s'il n'y en a pas."""
    service.remove_logo(tenant.session, tenant.ctx, ip_address=client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
