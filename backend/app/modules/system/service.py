"""Façade de services du module System. Lecture seule, sans effet de bord."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tenancy import TenantContext
from app.modules.system.repository import OutboxHealthRepository
from app.modules.system.schemas import OutboxHealth


def outbox_health(session: Session, ctx: TenantContext) -> OutboxHealth:
    """État de l'outbox de l'entreprise du contexte.

    `dead_lettered` compte les événements qui ont épuisé leurs tentatives. Le seuil
    vient de la configuration, mais il est aussi porté par un `CHECK` en base
    (`attempts <= 10`) : l'un peut être plus prudent que l'autre, jamais plus laxiste.
    """
    health = OutboxHealthRepository(session, ctx).health(
        max_attempts=get_settings().outbox_max_attempts
    )
    return OutboxHealth.model_validate(health)
