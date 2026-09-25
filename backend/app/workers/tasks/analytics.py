"""Consommateurs analytiques : reconstruction des faits et invalidation du cache.

Ces tâches tournent sous le rôle **`coges_analytics`** : c'est le seul du projet
autorisé à `DELETE`, et seulement sur `daily_sales_facts`, une projection
intégralement reconstruisible (§ 8.11, ADR 0032). `coges_app` ne pourrait pas purger
un fait devenu vide — il laisserait un fait fantôme, et **T31** échouerait.

Le jour à réécrire vient de `sold_at`, lu dans le **corps de l'événement** : jamais
`cancelled_at`, jamais `returned_at`. Un retour enregistré aujourd'hui corrige une
journée d'il y a trois semaines (§ 4.10), et c'est cette journée-là qu'il faut
réécrire.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.database import get_analytics_session_factory
from app.core.events.inbox import Event, handle
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.analytics import service as analytics_service
from app.modules.dashboard import service as dashboard_service
from app.workers.celery_app import celery_app
from app.workers.subscriptions import INVALIDATE_DASHBOARD, REBUILD_SALE_DAY

logger = logging.getLogger(__name__)

#: Nom du consommateur dans `processed_events`. Il identifie **l'effet**, pas la
#: tâche : deux tâches qui produiraient le même effet devraient partager ce nom.
CONSUMER = "analytics.facts"


def _sold_day(session: Session, ctx: TenantContext, event: Event) -> date | None:
    """Jour de vente porté par l'événement, dans le fuseau de l'entreprise."""
    raw = event.payload.get("sold_at")
    if not isinstance(raw, str):
        # Aucun des trois types abonnés ne peut en manquer : le contrat est écrit
        # dans `app/modules/sales/events.py`. Si cela arrive, c'est l'émetteur qui a
        # changé, et le dire vaut mieux que réécrire un jour arbitraire.
        logger.error(
            "Événement sans `sold_at` : aucun jour à reconstruire",
            extra={"event_id": event.id, "event_type": event.event_type.value},
        )
        return None
    return analytics_service.day_of(session, ctx, sold_at=datetime.fromisoformat(raw))


@celery_app.task(name=REBUILD_SALE_DAY, bind=True, max_retries=3, default_retry_delay=30)
def rebuild_sale_day(self: Any, **message: Any) -> str:
    """Réécrit la journée de vente touchée par l'événement.

    Idempotent par construction : la marque `processed_events` commite avec l'effet,
    et la requête du § 6.1 rejouée sur la même plage donne le même résultat (**T30**).
    Un rejeu ne peut donc ni dupliquer, ni décaler un chiffre.
    """
    event = Event.from_message(**message)
    factory = get_analytics_session_factory()

    def _rebuild(session: Session, ctx: TenantContext, received: Event) -> None:
        day = _sold_day(session, ctx, received)
        if day is None:
            return
        analytics_service.rebuild_days(session, ctx, days=[day])
        logger.info(
            "Faits reconstruits",
            extra={"company_id": str(ctx.company_id), "day": day.isoformat()},
        )

    try:
        fresh = handle(event, consumer=CONSUMER, handler=_rebuild, session_factory=factory)
    except Exception as exc:  # pragma: no cover - dépend de la base
        raise self.retry(exc=exc) from exc

    # L'invalidation est **hors** de la transaction : le cache ne doit pas être vidé
    # tant que les faits ne sont pas commités, sinon une lecture concurrente le
    # remplirait aussitôt avec les anciens chiffres.
    dashboard_service.invalidate(event.company_id)
    return "rebuilt" if fresh else "already-processed"


@celery_app.task(name=INVALIDATE_DASHBOARD)
def invalidate_dashboard(**message: Any) -> str:
    """Oublie le tableau de bord d'une entreprise après un fait qui le déplace.

    Trésorerie, créances, alertes de stock : ces mesures ne vivent pas dans
    `daily_sales_facts`, mais elles sont à l'écran d'accueil. Sans cette invalidation,
    un encaissement resterait invisible jusqu'à l'expiration du TTL.

    Pas de marque d'idempotence : vider un cache deux fois est vider un cache.
    """
    event = Event.from_message(**message)
    dashboard_service.invalidate(event.company_id)
    return "invalidated"


@celery_app.task(name="analytics.rebuild_recent_facts")
def rebuild_recent_facts(company_id: str, window_days: int) -> int:
    """Réécrit les `window_days` derniers jours d'une entreprise.

    C'est le filet du § 12.1 point 3 : un événement perdu produirait un agrégat
    silencieusement faux, qu'aucune contrainte SQL ne peut détecter. Le rejouer chaque
    nuit borne l'erreur possible à une nuit.
    """
    ctx = TenantContext.bootstrap(UUID(company_id))
    with tenant_transaction(ctx, session_factory=get_analytics_session_factory()) as session:
        today = analytics_service.today_in_company(session, ctx)
        days = [today - timedelta(days=offset) for offset in range(window_days)]
        analytics_service.rebuild_days(session, ctx, days=days)
    dashboard_service.invalidate(ctx.company_id)
    logger.info(
        "Filet analytique passé",
        extra={"company_id": company_id, "window_days": window_days},
    )
    return window_days
