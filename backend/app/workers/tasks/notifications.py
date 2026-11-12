"""Consommateurs d'alertes : stock bas, rupture, vente annulée, dette échue, connexions.

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

import httpx
from sqlalchemy.orm import Session

from app.core import webpush
from app.core.config import get_settings
from app.core.display import dmy, fcfa, qty, qty_with_unit
from app.core.events.inbox import Event, handle
from app.core.money import serialize
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.finance import service as finance_service
from app.modules.notifications import service as notifications_service
from app.modules.notifications.schemas import NotificationType
from app.modules.products import service as products_service
from app.modules.users import service as users_service
from app.workers.beat import SCAN_DUE_DEBTS
from app.workers.celery_app import celery_app
from app.workers.jobs import tracked_job
from app.workers.subscriptions import ON_SALE_CANCELLED, ON_STOCK_UPDATED
from app.workers.tenants import each_company

logger = logging.getLogger(__name__)

#: Nom repris tel quel par `app.modules.auth.service`, qui l'enfile sans importer le worker.
LOGIN_FAILURES = "notifications.login_failures"

STOCK_CONSUMER = "notifications.stock"
CANCELLED_CONSUMER = "notifications.sale_cancelled"


@celery_app.task(name=ON_STOCK_UPDATED, bind=True, max_retries=3, default_retry_delay=30)
def on_stock_updated(self: Any, **message: Any) -> str:
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

        # Mots de la maquette v2 (écran 23, ADR 0074), sans accord : on ne connaît pas
        # le genre d'un article (« Huile », « Riz »).
        texts = notifications_service.push_texts
        if on_hand <= 0:
            kind = NotificationType.STOCK_OUT
            title = f"{label} : plus en stock"
            body = "Vous ne pouvez plus en vendre."
            push = texts.stock_out(label, product_id)
        else:
            kind = NotificationType.STOCK_LOW
            threshold = summary.reorder_point if summary is not None else None
            title = f"{label} : plus que {qty(on_hand)}"
            body = (
                f"Sous votre seuil d'alerte de {qty(threshold)}"
                if threshold is not None
                else "Sous votre seuil d'alerte"
            )
            unit = summary.unit if summary is not None else ""
            push = texts.stock_low(label, qty_with_unit(on_hand, unit), product_id)

        sent = notifications_service.notify(
            session,
            ctx,
            notification_type=kind,
            title=title,
            body=body,
            entity_id=str(product_id),
            data={"product_id": str(product_id), "qty_on_hand": serialize(on_hand)},
            push=push,
        )
        logger.info(
            "Alerte de stock",
            extra={"company_id": str(ctx.company_id), "type": kind.value, "recipients": sent},
        )

    try:
        fresh = handle(event, consumer=STOCK_CONSUMER, handler=_alert)
    except Exception as exc:
        # Comme l'analytique : une base qui flanche ne perd pas l'alerte (ADR 0088).
        raise self.retry(exc=exc) from exc
    return "handled" if fresh else "already-processed"


@celery_app.task(name=ON_SALE_CANCELLED, bind=True, max_retries=3, default_retry_delay=30)
def on_sale_cancelled(self: Any, **message: Any) -> str:
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
        number = sale_no.split("-")[-1].lstrip("0") or sale_no
        body = f"Raison : {reason[:1].lower()}{reason[1:]}" if reason else "Sans raison donnée"
        # Qui a annulé : `cancelled_by_user_id` (ADR 0120), ou celui qui a corrigé (ADR
        # 0119). Absent des événements plus anciens.
        corrected = bool(payload.get("corrected"))
        raw_actor = payload.get("cancelled_by_user_id") or payload.get("corrected_by_user_id")
        actor = UUID(str(raw_actor)) if raw_actor else None
        name = users_service.names_by_id(session, ctx, [actor]).get(actor) if actor else None
        # Une correction n'est jamais silencieuse : l'alerte nomme qui l'a faite (ADR 0119).
        if corrected:
            body = f"Corrigée par {name}" if name else "Corrigée"
        notifications_service.notify(
            session,
            ctx,
            notification_type=NotificationType.SALE_CANCELLED,
            title=f"Vente n° {number} annulée ({fcfa(amount)})",
            body=body,
            entity_id=str(received.aggregate_id),
            data={"sale_id": str(received.aggregate_id), "sale_no": sale_no, "total": total},
            push=notifications_service.push_texts.sale_cancelled(
                number, name, corrected=corrected, sale_id=received.aggregate_id
            ),
            actor_user_id=actor,
        )

    try:
        fresh = handle(event, consumer=CANCELLED_CONSUMER, handler=_alert)
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    return "handled" if fresh else "already-processed"


@celery_app.task(name=LOGIN_FAILURES, bind=True, max_retries=3, default_retry_delay=30)
def login_failures(self: Any, company_id: str, user_id: str, failures: int) -> int:
    """Échecs de connexion répétés sur un compte réel (ADR 0078), enfilés par Auth.

    Une alerte par heure au plus et par compte visé : le dédoublonnage est raccourci
    à une heure, la clé est le compte. Un compte disparu entre-temps n'alerte personne.
    """
    try:
        ctx = TenantContext.bootstrap(UUID(company_id))
        with tenant_transaction(ctx) as session:
            names = users_service.names_by_id(session, ctx, [UUID(user_id)])
            name = names.get(UUID(user_id))
            if name is None:
                return 0
            return notifications_service.notify(
                session,
                ctx,
                notification_type=NotificationType.LOGIN_FAILURES,
                title=f"Plusieurs tentatives de connexion échouées sur le compte de {name}"[:160],
                body=(
                    "Si ce n’est pas cette personne, donnez-lui un nouveau mot de passe "
                    "ou coupez son accès."
                ),
                entity_id=user_id,
                data={"user_id": user_id, "failures": failures},
                push=notifications_service.push_texts.login_failures(name),
                dedupe_hours=1,
            )
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(name="notifications.scan_due_debts")
@tracked_job("notifications.scan_due_debts", ping_as=SCAN_DUE_DEBTS)
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
        debts = list(finance_service.debts_due(session, ctx, on=reference))
        names = finance_service.party_names_of_debts(session, ctx, debts)
        for debt in debts:
            due_date = debt.due_date.isoformat() if debt.due_date else ""
            name = names.get(debt.id)
            customer = debt.party_type == "customer"
            # Maquette v2, écran 23 (ADR 0074) : la personne d'abord, en mots simples.
            if customer:
                title = f"{name} n'a pas payé à temps" if name else "Un client n'a pas payé à temps"
                body = (
                    f"{fcfa(debt.balance)} attendus depuis le {dmy(debt.due_date)}"
                    if debt.due_date
                    else f"{fcfa(debt.balance)} attendus"
                )
            else:
                title = f"{name} : à payer, date dépassée" if name else "Fournisseur à payer"
                body = (
                    f"{fcfa(debt.balance)} à payer avant le {dmy(debt.due_date)}"
                    if debt.due_date
                    else f"{fcfa(debt.balance)} à payer"
                )
            party_id = debt.customer_id or debt.supplier_id
            sent += notifications_service.notify(
                session,
                ctx,
                notification_type=NotificationType.DEBT_DUE,
                title=title,
                body=body,
                entity_id=str(debt.id),
                data={
                    "debt_id": str(debt.id),
                    "party_type": debt.party_type,
                    "party_id": str(party_id) if party_id else None,
                    "balance": serialize(debt.balance),
                    "due_date": due_date,
                },
                push=notifications_service.push_texts.debt_due(name, debt.party_type, party_id),
            )
    logger.info(
        "Balayage des dettes à payer",
        extra={"company_id": company_id, "notifications": sent},
    )
    return sent


@celery_app.task(name=SCAN_DUE_DEBTS)
@tracked_job(SCAN_DUE_DEBTS)
def scan_due_debts_all() -> int:
    """Éventail : une sous-tâche de dettes échues par entreprise."""
    count = 0
    for company_id in each_company():
        scan_due_debts.delay(str(company_id))
        count += 1
    return count


@celery_app.task(
    name=notifications_service.push_texts.PUSH_DELIVER,
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def push_deliver(self: Any, company_id: str, ids: list[str]) -> int:
    """Envoie sur les téléphones les alertes déjà validées (Web Push, ADR 0120).

    Trois temps, pour ne jamais tenir une transaction pendant un appel réseau : lire ce
    qui part, poster chez les services de push, puis noter les réponses (404 ou 410 :
    abonnement arrêté). Le plafond horaire par personne est compté dans Redis. Rend le
    nombre de messages remis à au moins un appareil.
    """
    settings = get_settings()
    if not settings.push_enabled or settings.vapid_private_key is None:
        return 0
    assert settings.vapid_subject is not None
    ctx = TenantContext.bootstrap(UUID(company_id))
    try:
        with tenant_transaction(ctx) as session:
            plan = notifications_service.push_plan(session, ctx, [UUID(item) for item in ids])
    except Exception as exc:
        raise self.retry(exc=exc) from exc

    private_key = settings.vapid_private_key.get_secret_value()
    results: list[tuple[UUID, webpush.PushResult]] = []
    delivered = 0
    with httpx.Client(timeout=settings.push_timeout_seconds) as client:
        for outgoing in plan:
            if not notifications_service.push_allowed_this_hour(ctx.company_id, outgoing.user_id):
                logger.info(
                    "Plafond horaire de notifications atteint", extra={"company_id": company_id}
                )
                continue
            message = {**outgoing.message.as_data(), "tag": "coges-alertes"}
            sent = False
            for subscription_id, target in outgoing.targets:
                result = webpush.send(
                    target,
                    message,
                    private_key=private_key,
                    subject=settings.vapid_subject,
                    client=client,
                )
                results.append((subscription_id, result))
                sent = sent or result.delivered
            delivered += int(sent)

    # Les réponses sont notées même si un envoi a échoué : un 410 arrête l'abonnement.
    with tenant_transaction(ctx) as session:
        notifications_service.record_push_results(session, ctx, results)
    return delivered
