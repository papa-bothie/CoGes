"""Exports volumineux — « Exports et documents : Worker, fichier mis à disposition en fin
de tâche » (Architecture, « Où s'exécute quoi »).

Le worker n'appelle jamais l'API (Diagramme 2, `B⇸A`) : il écrit le fichier dans
`export_files`, que l'API sert ensuite. Toute la logique vit dans la façade du module
Import/Export ; ces tâches n'ouvrent que la transaction et le contexte tenant.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.core.audit import AuditAction, audit_secondary
from app.core.errors import NotFoundError
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.importexport import service as importexport_service
from app.workers.beat import SWEEP_EXPORTS
from app.workers.celery_app import celery_app
from app.workers.jobs import tracked_job
from app.workers.tenants import each_company

logger = logging.getLogger(__name__)

#: La demande est enfilée par l'API avant le COMMIT de sa transaction : si la ligne
#: n'est pas encore visible, on réessaie un peu plus tard plutôt que d'échouer.
MISSING_ROW_RETRIES = 5


@celery_app.task(name="exports.build_sales", bind=True, max_retries=MISSING_ROW_RETRIES)
def build_sales(self: Any, *, company_id: str, user_id: str, export_id: str) -> str:
    """Produit le fichier d'un export de ventes, puis trace l'export (audit secondaire)."""
    ctx = TenantContext(user_id=UUID(user_id), company_id=UUID(company_id))
    try:
        with tenant_transaction(ctx) as session:
            status = importexport_service.build_sales_export(session, ctx, UUID(export_id))
            if status == "ready":
                audit_secondary(
                    session,
                    ctx,
                    action=AuditAction.EXPORT,
                    entity_table="export_files",
                    entity_id=UUID(export_id),
                    context={"kind": "sales"},
                )
    except NotFoundError as exc:
        raise self.retry(countdown=2**self.request.retries, exc=exc) from exc
    except Exception as exc:
        logger.error("Export en échec", extra={"export_id": export_id}, exc_info=True)
        with tenant_transaction(ctx) as session:
            importexport_service.mark_export_failed(
                session, ctx, UUID(export_id), f"{type(exc).__name__}"
            )
        return "failed"
    return status


@celery_app.task(name="exports.sweep")
@tracked_job("exports.sweep", ping_as=SWEEP_EXPORTS)
def sweep(company_id: str) -> int:
    """Vide les exports périmés d'une entreprise et renfile ceux restés en attente."""
    ctx = TenantContext.bootstrap(UUID(company_id))
    with tenant_transaction(ctx) as session:
        expired = importexport_service.expire_exports(session, ctx)
        pending = importexport_service.pending_export_ids(session, ctx)
        requested_by = importexport_service.requesters(session, ctx, pending)
    for export_id in pending:
        build_sales.delay(
            company_id=company_id, user_id=str(requested_by[export_id]), export_id=str(export_id)
        )
    return expired


@celery_app.task(name=SWEEP_EXPORTS)
@tracked_job(SWEEP_EXPORTS)
def sweep_all() -> int:
    """Éventail nocturne du balayage des exports."""
    count = 0
    for company_id in each_company():
        sweep.delay(str(company_id))
        count += 1
    return count
