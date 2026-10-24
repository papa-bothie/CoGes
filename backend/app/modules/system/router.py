"""Routes HTTP du module System. Aucune requête SQL ici."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.deps import (
    PlatformSession,
    TenantSession,
    get_platform_session,
    require_ops_token,
    require_permission,
    require_platform_role,
)
from app.core.repository import MAX_PAGE_SIZE
from app.modules.system import service
from app.modules.system.schemas import (
    JobRunPage,
    OutboxHealth,
    PlatformOutbox,
    WorkersHealth,
)

router = APIRouter(prefix="/system", tags=["system"])

#: Routes de l'équipe CoGes (ADR 0090), même module, même service : l'administration
#: (`modules/platform/`) n'importe aucun module, la surveillance reste donc ici.
platform_router = APIRouter(prefix="/platform/system", tags=["platform-admin"])

#: Lecture seule, sans donnée d'entreprise : les deux profils de l'équipe.
Monitoring = Annotated[
    PlatformSession,
    Depends(require_platform_role("administrator", "support"), scope="function"),
]


def get_ops_now() -> datetime:
    """Horloge réelle du bilan (jamais `COGES_FROZEN_NOW`) ; surchargée par les tests."""
    return datetime.now(UTC)


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


_WORKERS_RESPONSES: dict[int | str, dict[str, object]] = {
    503: {"model": WorkersHealth, "description": "Au moins un problème détecté."}
}


def _workers_response(session: Session, now: datetime) -> JSONResponse:
    """200 si tout va bien, 503 sinon, avec le même corps — pour les deux portes."""
    health = service.workers_health(session, now=now)
    return JSONResponse(
        status_code=200 if health.healthy else 503,
        content=health.model_dump(mode="json"),
    )


@router.get("/workers", response_model=WorkersHealth, responses=_WORKERS_RESPONSES)
def workers_health(
    _: Annotated[None, Depends(require_ops_token)],
    session: Annotated[Session, Depends(get_platform_session, scope="function")],
    now: Annotated[datetime, Depends(get_ops_now)],
) -> JSONResponse:
    """Bilan des workers, de beat, du relais et des tâches de nuit (ADR 0077).

    Protégé par `COGES_OPS_TOKEN` (`Authorization: Bearer …`), pas par un compte :
    c'est l'exploitant qui interroge, depuis un terminal ou une surveillance externe.
    L'équipe passe par `/platform/system/workers` (ADR 0090) : même lecture, même
    réponse. Aucun nom ni identifiant d'entreprise n'y figure.
    """
    return _workers_response(session, now)


@platform_router.get("/workers", response_model=WorkersHealth, responses=_WORKERS_RESPONSES)
def platform_workers_health(
    platform: Monitoring, now: Annotated[datetime, Depends(get_ops_now)]
) -> JSONResponse:
    """Le même bilan que `/system/workers`, pour un compte de l'équipe (ADR 0090).

    Sous `/platform` : servi seulement sur le sous-domaine de l'administration, filtré
    par adresse IP. Lu sous `coges_app_platform`, par les mêmes fonctions d'agrégat.
    """
    return _workers_response(platform.session, now)


@platform_router.get("/job-runs", response_model=JobRunPage)
def job_runs(
    platform: Monitoring,
    job: Annotated[str | None, Query(max_length=100)] = None,
    status: Literal["ok", "failed", "running"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> JobRunPage:
    """Exécutions des tâches planifiées sur 90 jours, la plus récente d'abord.

    Une exécution restée `running` au-delà du délai d'une tâche est rendue `failed`.
    Une sous-tâche d'entreprise est signalée (`per_company`), jamais nommée.
    """
    return service.job_runs_page(
        platform.session, job=job, status=status, page=page, page_size=page_size
    )


@platform_router.get("/outbox", response_model=PlatformOutbox)
def outbox(
    platform: Monitoring,
    now: Annotated[datetime, Depends(get_ops_now)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> PlatformOutbox:
    """Retard du relais et événements au rebut, toutes entreprises confondues.

    Pour chaque événement au rebut : identifiant, type, date, tentatives — de quoi le
    rejouer à la main (`docs/runbooks/workers.md`). Jamais son contenu.
    """
    return service.platform_outbox(platform.session, page=page, page_size=page_size, now=now)
