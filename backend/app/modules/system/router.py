"""Routes HTTP du module System. Aucune requête SQL ici."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.deps import TenantSession, get_platform_session, require_ops_token, require_permission
from app.modules.system import service
from app.modules.system.schemas import OutboxHealth, WorkersHealth

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


@router.get(
    "/workers",
    response_model=WorkersHealth,
    responses={503: {"model": WorkersHealth, "description": "Au moins un problème détecté."}},
)
def workers_health(
    _: Annotated[None, Depends(require_ops_token)],
    session: Annotated[Session, Depends(get_platform_session, scope="function")],
) -> JSONResponse:
    """Bilan des workers, de beat, du relais et des tâches de nuit (ADR 0077).

    Protégé par `COGES_OPS_TOKEN` (`Authorization: Bearer …`), pas par un compte :
    c'est l'exploitant qui interroge. 200 si tout va bien, 503 sinon, avec le même
    corps. Aucun nom ni identifiant d'entreprise n'y figure.
    """
    health = service.workers_health(session)
    return JSONResponse(
        status_code=200 if health.healthy else 503,
        content=health.model_dump(mode="json"),
    )
