"""Routes HTTP du module Companies. Aucune requête SQL ici."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.deps import TenantSession, client_ip, require_permission
from app.modules.companies import service
from app.modules.companies.schemas import CompanyRead, CompanyUpdate

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/me", response_model=CompanyRead)
def read_current_company(
    tenant: Annotated[TenantSession, Depends(require_permission("company:read"))],
) -> CompanyRead:
    """Paramètres de l'entreprise de l'utilisateur connecté."""
    company = service.get_current_company(tenant.session, tenant.ctx)
    return CompanyRead.model_validate(company)


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
    return CompanyRead.model_validate(company)
