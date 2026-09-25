"""Route HTTP du module Dashboard. Aucune requête SQL ici."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import TenantSession, require_permission
from app.modules.dashboard import service
from app.modules.dashboard.schemas import Dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard)
def read_dashboard(
    tenant: Annotated[TenantSession, Depends(require_permission("dashboard:read"))],
) -> Dashboard:
    """Indicateurs d'accueil de l'entreprise.

    Servi sur des agrégats **déjà calculés** et un cache court par tenant : cible
    < 200 ms. Aucune période à saisir — c'est l'écran d'ouverture de la journée, pas
    un outil d'analyse ; pour cela, `/analytics`.
    """
    return service.dashboard(tenant.session, tenant.ctx)
