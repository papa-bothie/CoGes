"""Routes HTTP du module Import/Export. Aucune requête SQL ici.

* `POST /imports/{kind}` — téléversement (multipart, champ `file`), `?dry_run=true`
  pour l'aperçu. Le client renvoie ensuite **le même fichier** sans `dry_run` : l'API
  Vercel est sans état, rien n'est gardé entre les deux appels (ADR 0041).
* `GET /exports/referentials/{kind}` — référentiel complet, servi dans la requête.
* `POST /exports/sales` puis `GET /exports/{id}` et `GET /exports/{id}/file` — les
  ventes d'une période, produites par le worker.
"""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status

from app.core import idempotency, queue
from app.core.deps import TenantSession, client_ip, require_permission
from app.core.idempotency import IdempotencyKey
from app.core.tenancy import TenantContext
from app.modules.importexport import service
from app.modules.importexport.schemas import (
    ExportFormat,
    ExportList,
    ExportRead,
    ImportFingerprint,
    ImportKind,
    ImportReport,
    ReferentialKind,
    SalesExportCreate,
)

imports_router = APIRouter(prefix="/imports", tags=["imports"])
exports_router = APIRouter(prefix="/exports", tags=["exports"])

#: Gabarit de l'endpoint enregistré avec la clé (ADR 0039) : le type fait partie de
#: la ressource. L'empreinte, elle, porte le condensat du fichier.
IMPORT_ENDPOINT = "POST /api/v1/imports/{kind}"

#: Tâche worker qui produit un export de ventes, désignée par son nom.
BUILD_SALES_EXPORT_TASK = "exports.build_sales"
#: Audit secondaire (canal 2) : l'export est tracé après coup, par le worker.
AUDIT_TASK = "audit.record"


def _attachment(file: service.ExportedFile) -> Response:
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Content-Disposition": f'attachment; filename="{file.filename}"'},
    )


def _audit_export(
    ctx: TenantContext, request: Request, entity_id: UUID | None, **diff: object
) -> None:
    queue.enqueue(
        AUDIT_TASK,
        countdown=0,
        company_id=str(ctx.company_id),
        actor_user_id=str(ctx.user_id),
        action="export",
        entity_table="export_files",
        entity_id=str(entity_id) if entity_id else None,
        diff={key: str(value) for key, value in diff.items()},
        ip_address=client_ip(request),
    )


# ------------------------------------------------------------------- imports


@imports_router.post(
    "/{kind}",
    response_model=ImportReport,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": ImportReport, "description": "Simulation (dry_run)"}},
)
def import_file(
    kind: ImportKind,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("importexport:create"))],
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File(description="CSV (; ou ,) ou Excel .xlsx")],
    dry_run: Annotated[bool, Query()] = False,
) -> Response:
    """Importe un référentiel, tout ou rien ; `dry_run=true` rend le rapport sans écrire.

    Le stock initial d'un produit passe par un mouvement `initial` (façade
    Inventory), son prix par `product_prices` (façade Products). Un fichier fautif
    répond 422 `import_invalid` avec le rapport ligne par ligne, et n'écrit rien.

    `Idempotency-Key` est exigée, y compris en simulation, pour garder une seule règle
    côté client. Seul l'import réel l'enregistre : un aperçu n'a rien à rejouer.
    """
    content = file.file.read()
    if dry_run:
        report = service.import_file(
            tenant.session, tenant.ctx, kind, content, dry_run=True, ip_address=client_ip(request)
        )
        return Response(
            content=report.model_dump_json(), media_type="application/json", status_code=200
        )

    fingerprint = ImportFingerprint(kind=kind, sha256=hashlib.sha256(content).hexdigest())
    replay = idempotency.reserve(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        endpoint=IMPORT_ENDPOINT.format(kind=kind),
        payload=fingerprint,
    )
    if replay is not None:
        return idempotency.replay_response(replay)

    report = service.import_file(
        tenant.session, tenant.ctx, kind, content, dry_run=False, ip_address=client_ip(request)
    )
    return idempotency.completed(
        tenant.session,
        tenant.ctx,
        key=idempotency_key,
        status_code=status.HTTP_201_CREATED,
        model=report,
    )


@imports_router.get("/{kind}/template", response_class=Response)
def import_template(
    kind: ImportKind,
    tenant: Annotated[TenantSession, Depends(require_permission("importexport:create"))],
) -> Response:
    """Fichier CSV vide aux colonnes attendues pour ce type d'import."""
    return Response(
        content=service.import_template(kind),
        media_type=service.MEDIA_TYPES["csv"],
        headers={"Content-Disposition": f'attachment; filename="modele-{kind}.csv"'},
    )


# ------------------------------------------------------------------- exports


@exports_router.get("/referentials/{kind}", response_class=Response)
def export_referential(
    kind: ReferentialKind,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("importexport:export"))],
    format: Annotated[ExportFormat, Query()] = "xlsx",  # noqa: A002 - nom du paramètre public
) -> Response:
    """Référentiel complet, aux colonnes de l'import. 409 au-delà de 10 000 lignes."""
    exported = service.export_referential(tenant.session, tenant.ctx, kind, format)
    _audit_export(tenant.ctx, request, None, kind=kind, format=format, rows=exported.row_count)
    return _attachment(exported)


@exports_router.post("/sales", response_model=ExportRead, status_code=status.HTTP_202_ACCEPTED)
def request_sales_export(
    payload: SalesExportCreate,
    tenant: Annotated[TenantSession, Depends(require_permission("importexport:export"))],
) -> ExportRead:
    """Demande l'export des ventes d'une période ; le fichier est produit par le worker."""
    export = service.request_sales_export(tenant.session, tenant.ctx, payload)
    queue.enqueue(
        BUILD_SALES_EXPORT_TASK,
        company_id=str(tenant.ctx.company_id),
        user_id=str(tenant.ctx.user_id),
        export_id=str(export.id),
    )
    return ExportRead.model_validate(export)


@exports_router.get("", response_model=ExportList)
def list_exports(
    tenant: Annotated[TenantSession, Depends(require_permission("importexport:export"))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ExportList:
    """Derniers exports demandés, du plus récent au plus ancien."""
    exports = service.list_exports(tenant.session, tenant.ctx, limit=limit)
    return ExportList(items=[ExportRead.model_validate(export) for export in exports])


@exports_router.get("/{export_id}", response_model=ExportRead)
def get_export(
    export_id: UUID,
    tenant: Annotated[TenantSession, Depends(require_permission("importexport:export"))],
) -> ExportRead:
    """État d'un export : `pending`, `ready`, `failed` ou `expired`."""
    return ExportRead.model_validate(service.get_export(tenant.session, tenant.ctx, export_id))


@exports_router.get("/{export_id}/file", response_class=Response)
def download_export(
    export_id: UUID,
    request: Request,
    tenant: Annotated[TenantSession, Depends(require_permission("importexport:export"))],
) -> Response:
    """Le fichier d'un export prêt. 409 `export_not_ready` sinon ; 404 chez un autre tenant."""
    exported = service.export_content(tenant.session, tenant.ctx, export_id)
    _audit_export(tenant.ctx, request, export_id, download=True, rows=exported.row_count)
    return _attachment(exported)
