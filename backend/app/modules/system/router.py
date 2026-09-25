"""Routes HTTP du module System. Aucune requête SQL ici."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import TenantSession, require_permission
from app.modules.system import service
from app.modules.system.schemas import OutboxHealth

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/outbox", response_model=OutboxHealth)
def outbox_health(
    tenant: Annotated[TenantSession, Depends(require_permission("system:read"))],
) -> OutboxHealth:
    """Santé du chemin asynchrone de l'entreprise.

    Lecture seule et **gérant seul**. Il n'existe pas de route pour rejouer un
    événement : un rejeu se décide après avoir corrigé la cause, et se fait
    délibérément, pas depuis un tableau de bord.
    """
    return service.outbox_health(tenant.session, tenant.ctx)
