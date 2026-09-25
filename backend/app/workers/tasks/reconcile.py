"""Tâches planifiées : réalignement, réconciliation, partitions, purges.

Toutes suivent la même forme — un **éventail** demande la liste des entreprises à
`active_company_ids()` et enfile une sous-tâche par entreprise, chacune ouvrant sa
propre transaction avec son propre contexte tenant (Diagramme 8). Aucune tâche ne
traite deux entreprises dans une même transaction ; pour `rebuild_product_stock`,
c'est même impossible : sa table temporaire est `ON COMMIT DROP`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.database import get_analytics_session_factory
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.analytics import service as analytics_service
from app.modules.analytics.repository import DailySalesFactRepository
from app.modules.inventory import service as inventory_service
from app.modules.sales import service as sales_service
from app.workers.beat import (
    CHECK_REVENUE,
    ENSURE_PARTITIONS,
    NIGHTLY_FACTS_WINDOW_DAYS,
    PURGE_IDEMPOTENCY,
    REBUILD_RECENT_FACTS,
    REBUILD_STOCK,
    RECONCILIATION_WINDOW_DAYS,
)
from app.workers.celery_app import celery_app
from app.workers.tasks.analytics import rebuild_recent_facts
from app.workers.tenants import each_company

logger = logging.getLogger(__name__)

#: Écart maximal toléré entre les agrégats et le calcul direct (§ 12.1 point 3).
#: Un centime : les deux sources somment les mêmes valeurs arrondies à la ligne, donc
#: l'écart attendu est **nul**. La tolérance existe pour ne pas alerter sur un
#: arrondi, pas pour absorber une erreur de construction.
REVENUE_TOLERANCE = Decimal("0.01")

_PURGE_IDEMPOTENCY_KEYS = text("SELECT purge_expired_idempotency_keys() AS purged")
_ENSURE_PARTITION = text("SELECT ensure_audit_partition(CAST(:day AS date))")


# ----------------------------------------------------------- projection de stock


@celery_app.task(name="reconcile.rebuild_stock")
def rebuild_stock(company_id: str) -> int:
    """Rejoue le journal d'une entreprise et réaligne sa projection (§ 5.7).

    Le CMP dépend de l'ordre des mouvements : un antidatage, même borné à 48 h
    (ADR 0015), peut laisser la projection courante différente du recalcul. Cette
    tâche remet les deux d'accord et `recomputed_at` atteste du passage.

    Renvoie le nombre de produits qui divergeaient — zéro est la normale, et une
    valeur non nulle mérite d'être lue.
    """
    ctx = TenantContext.bootstrap(UUID(company_id))
    with tenant_transaction(ctx) as session:
        divergences = inventory_service.rebuild_stock(session, ctx)
    if divergences:
        logger.warning(
            "Projection de stock réalignée",
            extra={"company_id": company_id, "products": len(divergences)},
        )
    return len(divergences)


@celery_app.task(name=REBUILD_STOCK)
def rebuild_stock_all() -> int:
    """Éventail nocturne du réalignement de stock."""
    return _fan_out(rebuild_stock.delay, job="rebuild_stock")


# --------------------------------------------------------------- filet analytique


@celery_app.task(name=REBUILD_RECENT_FACTS)
def rebuild_recent_facts_all() -> int:
    """Éventail nocturne du filet analytique, sur une fenêtre glissante."""
    count = 0
    for company_id in each_company():
        rebuild_recent_facts.delay(str(company_id), NIGHTLY_FACTS_WINDOW_DAYS)
        count += 1
    return count


# ------------------------------------------------------- réconciliation T32


@celery_app.task(name="reconcile.check_revenue")
def check_revenue(company_id: str, window_days: int = RECONCILIATION_WINDOW_DAYS) -> str:
    """Compare `daily_sales_facts` au calcul direct sur la fenêtre. C'est **T32**.

    Le § 12.1 point 3 le dit sans détour : un événement manquant produit un agrégat
    silencieusement faux, et **aucune contrainte SQL ne peut détecter cela**. Ce
    contrôle est la seule chose qui puisse.

    L'écart est un défaut technique, pas une nouvelle du commerce : il part en journal
    d'alerte et se lit dans `/api/v1/system/outbox`, il ne réveille pas un gérant qui
    n'a aucune action à entreprendre (ADR 0033).
    """
    ctx = TenantContext.bootstrap(UUID(company_id))
    with tenant_transaction(ctx, session_factory=get_analytics_session_factory()) as session:
        today = analytics_service.today_in_company(session, ctx)
        period_from = today - timedelta(days=window_days - 1)

        aggregated = DailySalesFactRepository(session, ctx).period_totals(
            period_from=period_from, period_to=today
        )["net_revenue"]
        start, end = analytics_service.period_bounds(
            session, ctx, period_from=period_from, period_to=today
        )
        direct = sales_service.revenue_totals(session, ctx, period_from=start, period_to=end)[
            "net_revenue"
        ]

    gap = abs(aggregated - direct)
    context: dict[str, Any] = {
        "company_id": company_id,
        "window_days": window_days,
        "aggregated": str(aggregated),
        "direct": str(direct),
        "gap": str(gap),
    }
    if gap > REVENUE_TOLERANCE:
        logger.error("Écart de réconciliation du chiffre d'affaires", extra=context)
        return "diverged"
    logger.info("Réconciliation du chiffre d'affaires conforme", extra=context)
    return "ok"


@celery_app.task(name=CHECK_REVENUE)
def check_revenue_all() -> int:
    """Éventail hebdomadaire du contrôle T32."""
    return _fan_out(check_revenue.delay, job="check_revenue")


# --------------------------------------------------------- partitions et purges


@celery_app.task(name=ENSURE_PARTITIONS)
def ensure_audit_partitions() -> str:
    """Crée la partition `audit_logs` du mois suivant.

    Le contexte tenant est posé sur l'entreprise nulle : la fonction est
    `SECURITY DEFINER` et les partitions ne sont pas tenant-scoped, mais toute
    transaction du projet passe par `tenant_transaction` — une seule voie, sans
    exception, est ce qui rend le § 12.1 point 1 vérifiable.

    Sans elle, tout INSERT dans `audit_logs` échouerait — donc toute vente, tout
    paiement, toute opération à audit critique. La partition `DEFAULT` posée en
    phase 02 est le filet qui empêche une panne de batch de devenir une panne de
    caisse (ADR 0008) ; cette tâche fait en sorte qu'il ne serve jamais.

    """
    today = datetime.now(UTC).date()
    # Le premier jour du mois suivant, atteint en passant par la fin du mois courant.
    next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    ctx = TenantContext.bootstrap(UUID(int=0))
    with tenant_transaction(ctx) as session:
        session.execute(_ENSURE_PARTITION, {"day": next_month})
    logger.info("Partition d'audit garantie", extra={"month": next_month.isoformat()})
    return next_month.isoformat()


@celery_app.task(name=PURGE_IDEMPOTENCY)
def purge_idempotency_keys() -> int:
    """Supprime les clés d'idempotence expirées — la dette laissée par l'ADR 0027.

    Une clé gardée trop longtemps n'a jamais rendu une mauvaise réponse ; c'est
    l'inverse qui serait dangereux. La purge ne touche donc que ce qui a dépassé
    `expires_at`, jamais une clé encore susceptible de servir à un rejeu.

    Pas d'éventail ici, et c'est délibéré : `coges_app` n'a le droit DELETE nulle
    part, la suppression passe donc par `purge_expired_idempotency_keys()`, une
    fonction `SECURITY DEFINER` qui balaye tout le cluster d'un coup. Une clé expirée
    n'appartient plus à personne.
    """
    ctx = TenantContext.bootstrap(UUID(int=0))
    with tenant_transaction(ctx) as session:
        purged = int(session.execute(_PURGE_IDEMPOTENCY_KEYS).scalar_one())
    if purged:
        logger.info("Clés d'idempotence purgées", extra={"purged": purged})
    return purged


def _fan_out(enqueue: Any, *, job: str) -> int:
    """Enfile une sous-tâche par entreprise et renvoie le compte."""
    count = 0
    for company_id in each_company():
        enqueue(str(company_id))
        count += 1
    logger.info("Éventail enfilé", extra={"job": job, "companies": count})
    return count


__all__ = [
    "check_revenue",
    "check_revenue_all",
    "ensure_audit_partitions",
    "purge_idempotency_keys",
    "rebuild_recent_facts_all",
    "rebuild_stock",
    "rebuild_stock_all",
]
