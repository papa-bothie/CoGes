"""Audit secondaire — le canal 2 de la Figure 7.

Ce que ce canal porte : connexions, exports, consultations sensibles, enrichissement
de contexte. Ce qu'il ne porte **jamais** : la preuve d'une opération critique. Une
vente, un paiement, une dette, un changement de droit écrivent leur trace dans la
**transaction** qui les produit (`app/core/audit.py`) et ne dépendent donc ni de
Redis, ni d'un worker, ni de cette tâche.

La différence est une garantie, pas une nuance : ce canal tolère un retard et une
reprise, le canal critique n'en tolère aucun.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.core.audit import AuditAction, audit_secondary
from app.core.tenancy import NIL_USER_ID, TenantContext, tenant_transaction
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

#: Actions que ce canal accepte. La liste est fermée : y glisser `confirm`, `cancel`
#: ou `delete` reviendrait à déplacer une preuve critique dans un canal qui peut
#: perdre un message, et la Figure 7 l'interdit.
SECONDARY_ACTIONS = frozenset({AuditAction.LOGIN, AuditAction.EXPORT, AuditAction.REBUILD})


@celery_app.task(name="audit.record")
def record(
    *,
    company_id: str,
    actor_user_id: str | None,
    action: str,
    entity_table: str,
    entity_id: str | None = None,
    diff: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> str:
    """Écrit une ligne d'audit secondaire, après COMMIT de l'opération d'origine.

    Refuse une action réservée au canal critique plutôt que de l'écrire ici : une
    trace critique arrivée par ce chemin serait une trace **que l'on croit** garantie.
    """
    verb = AuditAction(action)
    if verb not in SECONDARY_ACTIONS:
        logger.error(
            "Action refusée par l'audit secondaire : elle relève du canal critique",
            extra={"action": action, "entity_table": entity_table},
        )
        return "rejected"

    # L'acteur est porté par le contexte, comme partout ailleurs : `audit_logs` lit
    # `ctx.user_id`. Une action système sans acteur garde l'utilisateur nul.
    ctx = TenantContext(
        user_id=UUID(actor_user_id) if actor_user_id else NIL_USER_ID,
        company_id=UUID(company_id),
    )
    with tenant_transaction(ctx) as session:
        audit_secondary(
            session,
            ctx,
            action=verb,
            entity_table=entity_table,
            entity_id=UUID(entity_id) if entity_id else None,
            context=diff,
            ip_address=ip_address,
        )
    return "recorded"
