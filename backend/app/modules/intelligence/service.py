"""Façade de services du module Intelligence.

Les autres modules passent **par ici** ou par `serving`, jamais par le repository ni
les modèles. La seule écriture applicative du module est le statut d'un insight
(§ 4.12) ; tout le reste est écrit par le pipeline (`pipelines/`), dans le worker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.core.tenancy import TenantContext
from app.modules.intelligence import serving
from app.modules.intelligence.repository import InsightRepository
from app.modules.intelligence.schemas import InsightRead, InsightStatus, InsightStatusChange


class IntelligenceDisabledError(BusinessRuleError):
    code = "intelligence_disabled"
    default_message = "CoGes Intelligence est désactivée pour cette entreprise."


class InsightClosedError(BusinessRuleError):
    code = "insight_closed"
    default_message = "Cet insight est déjà écarté ou résolu : son statut ne change plus."


#: Un insight écarté ou résolu est clos. Le rouvrir pourrait heurter l'insight vivant
#: réémis depuis sous la même clé (index partiel `insights_dedupe_uq`).
CLOSED = (InsightStatus.DISMISSED.value, InsightStatus.RESOLVED.value)


def set_insight_status(
    session: Session,
    ctx: TenantContext,
    insight_id: UUID,
    status: InsightStatusChange,
    *,
    now: datetime | None = None,
) -> InsightRead:
    """Change le statut d'un insight. Aucune autre colonne n'est modifiable.

    `read_at` est posé au premier changement (un insight acquitté a été lu) ;
    `resolved_at` accompagne `resolved`, comme l'exigent les CHECK croisés du § 8.9.
    Autre entreprise ⇒ 404, jamais 403.
    """
    if not serving.is_enabled(session, ctx):
        raise IntelligenceDisabledError()
    insight = InsightRepository(session, ctx).get_for_update(insight_id)
    if insight is None:
        raise NotFoundError("Insight introuvable.")
    if insight.status in CLOSED:
        raise InsightClosedError()

    moment = now or datetime.now(UTC)
    insight.status = status.value
    if insight.read_at is None:
        insight.read_at = moment
    if status is InsightStatusChange.RESOLVED:
        insight.resolved_at = moment
    session.flush()
    return serving.insight_read(insight)
