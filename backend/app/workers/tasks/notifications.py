"""Consommateurs d'alertes : stock bas, rupture, vente annulée, dette échue.

Tournent sous `coges_app` : une alerte est un INSERT, jamais une suppression.

Deux origines, et elles ne se recouvrent pas. Les trois premières naissent d'un
**événement** — quelque chose vient d'arriver. La quatrième naît d'un **calendrier** :
une dette arrive à échéance précisément quand rien ne bouge, donc aucun événement ne
peut la signaler.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.display import dmy, fcfa, qty
from app.core.events.inbox import Event, handle
from app.core.money import serialize
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.finance import service as finance_service
from app.modules.notifications import service as notifications_service
from app.modules.notifications.schemas import NotificationType
from app.modules.products import service as products_service
from app.workers.beat import SCAN_DUE_DEBTS
from app.workers.celery_app import celery_app
from app.workers.subscriptions import ON_SALE_CANCELLED, ON_STOCK_UPDATED
from app.workers.tenants import each_company

logger = logging.getLogger(__name__)

STOCK_CONSUMER = "notifications.stock"
CANCELLED_CONSUMER = "notifications.sale_cancelled"


@celery_app.task(name=ON_STOCK_UPDATED)
def on_stock_updated(**message: Any) -> str:
    """Alerte de stock bas ou de rupture, si le mouvement a franchi le seuil.

    `below_reorder_point` et `qty_on_hand` viennent du corps de l'événement : aucun
    besoin de relire la projection, qui aurait d'ailleurs pu bouger depuis. Un abonné
    qui doit requêter la base pour comprendre son événement n'est plus découplé de
    l'émetteur (`app/modules/inventory/events.py`).
    """
    event = Event.from_message(**message)

    def _alert(session: Session, ctx: TenantContext, received: Event) -> None:
        payload = received.payload
        on_hand = Decimal(str(payload.get("qty_on_hand", "0")))
        below = bool(payload.get("below_reorder_point", False))
        if on_hand > 0 and not below:
            # Situation normale : pas d'alerte, mais la marque d'idempotence est
            # tout de même posée. C'est voulu — « rien à faire » est un traitement.
            return

        product_id = UUID(str(payload["product_id"]))
        names = products_service.get_summaries(session, ctx, [product_id])
        summary = names.get(product_id)
        label = summary.name if summary is not None else "Produit"

        if on_hand <= 0:
            kind = NotificationType.STOCK_OUT
            title = f"Rupture de stock — {label}"
            body = f"{label} n'est plus disponible."
        else:
            kind = NotificationType.STOCK_LOW
            title = f"Stock bas — {label}"
            body = f"Il reste {qty(on_hand)} de {label}, au niveau du seuil d'alerte."

        sent = notifications_service.notify(
            session,
            ctx,
            notification_type=kind,
            title=title,
            body=body,
            entity_id=str(product_id),
            data={"product_id": str(product_id), "qty_on_hand": serialize(on_hand)},
        )
        logger.info(
            "Alerte de stock",
            extra={"company_id": str(ctx.company_id), "type": kind.value, "recipients": sent},
        )

    fresh = handle(event, consumer=STOCK_CONSUMER, handler=_alert)
    return "handled" if fresh else "already-processed"


@celery_app.task(name=ON_SALE_CANCELLED)
def on_sale_cancelled(**message: Any) -> str:
    """Prévient ceux qui peuvent annuler une vente qu'une vente a été annulée.

    L'annulation touche à la fois le stock, la finance et la dette (ADR 0007) : elle
    mérite une trace visible, en plus de son audit critique. La notification ne
    **remplace** jamais cet audit — elle est jetable, lui ne l'est pas (§ 6).
    """
    event = Event.from_message(**message)

    def _alert(session: Session, ctx: TenantContext, received: Event) -> None:
        payload = received.payload
        sale_no = str(payload.get("sale_no", ""))
        amount = Decimal(str(payload.get("total", "0")))
        total = serialize(amount)
        reason = str(payload.get("reason", "")).strip()
        notifications_service.notify(
            session,
            ctx,
            notification_type=NotificationType.SALE_CANCELLED,
            title=f"Vente annulée — {sale_no}",
            body=f"La vente {sale_no} ({fcfa(amount)}) a été annulée. Pourquoi : {reason}"
            if reason
            else f"La vente {sale_no} ({fcfa(amount)}) a été annulée.",
            entity_id=str(received.aggregate_id),
            data={"sale_id": str(received.aggregate_id), "sale_no": sale_no, "total": total},
        )

    fresh = handle(event, consumer=CANCELLED_CONSUMER, handler=_alert)
    return "handled" if fresh else "already-processed"


@celery_app.task(name="notifications.scan_due_debts")
def scan_due_debts(company_id: str, today: str | None = None) -> int:
    """Alerte sur les créances et dettes arrivées à échéance dans une entreprise.

    Le dédoublonnage de 24 h du module Notifications fait le reste : une dette échue
    depuis trois semaines ne produit qu'une alerte par jour, pas vingt et une d'un
    coup au premier passage.
    """
    ctx = TenantContext.bootstrap(UUID(company_id))
    reference = date.fromisoformat(today) if today else None
    sent = 0
    with tenant_transaction(ctx) as session:
        for debt in finance_service.debts_due(session, ctx, on=reference):
            due_date = debt.due_date.isoformat() if debt.due_date else ""
            sent += notifications_service.notify(
                session,
                ctx,
                notification_type=NotificationType.DEBT_DUE,
                title="Dette à payer : date dépassée",
                body=(
                    f"Une dette de {fcfa(debt.balance)} devait être payée "
                    f"avant le {dmy(debt.due_date)}."
                    if debt.due_date
                    else f"Une dette de {fcfa(debt.balance)} n'est pas encore payée."
                ),
                entity_id=str(debt.id),
                data={
                    "debt_id": str(debt.id),
                    "party_type": debt.party_type,
                    "balance": serialize(debt.balance),
                    "due_date": due_date,
                },
            )
    logger.info(
        "Balayage des dettes à payer",
        extra={"company_id": company_id, "notifications": sent},
    )
    return sent


@celery_app.task(name=SCAN_DUE_DEBTS)
def scan_due_debts_all() -> int:
    """Éventail : une sous-tâche de dettes échues par entreprise."""
    count = 0
    for company_id in each_company():
        scan_due_debts.delay(str(company_id))
        count += 1
    return count
