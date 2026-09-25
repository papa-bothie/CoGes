"""Énumération des entreprises, pour les tâches planifiées.

Un batch nocturne doit passer sur **toutes** les entreprises, or `companies` est en
FORCE ROW LEVEL SECURITY avec une politique sur `id` : sans contexte, la table est
vide, y compris pour son propriétaire (ADR 0005, mesuré).

`active_company_ids()` est une fonction `SECURITY DEFINER` appartenant à `coges_bus`
qui ne rend **que des identifiants** — aucune donnée métier ne franchit la barrière
(ADR 0032). Le reste du traitement se fait ensuite entreprise par entreprise, sous
RLS normale, dans une transaction par entreprise.

Déduire la liste des seules entreprises ayant émis un événement aurait évité cette
fonction, mais une dette arrive à échéance précisément quand rien ne bouge : une
entreprise calme n'aurait jamais reçu ses alertes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_session_factory
from app.core.tenancy import TenantContext, tenant_transaction

logger = logging.getLogger(__name__)

_ACTIVE_COMPANIES = text("SELECT company_id FROM active_company_ids()")


def active_company_ids(session_factory: sessionmaker[Any] | None = None) -> list[UUID]:
    """Identifiants des entreprises vivantes."""
    factory = session_factory or get_session_factory()
    session: Session = factory()
    try:
        with session.begin():
            return list(session.execute(_ACTIVE_COMPANIES).scalars().all())
    finally:
        session.close()


def for_each_company(
    handler: Callable[[Session, TenantContext], None],
    *,
    job: str,
    session_factory: sessionmaker[Any] | None = None,
) -> int:
    """Exécute `handler` une fois par entreprise, **une transaction chacune**.

    Une entreprise qui échoue n'arrête pas les autres : sa transaction est annulée,
    l'incident journalisé, et le balayage continue. Un batch qui s'interrompt à la
    troisième entreprise sur quarante laisserait trente-sept gérants sans alertes,
    pour une erreur qui ne les concerne pas.

    Renvoie le nombre d'entreprises traitées sans erreur.
    """
    done = 0
    for company_id in active_company_ids(session_factory):
        try:
            ctx = TenantContext.bootstrap(company_id)
            with tenant_transaction(ctx, session_factory=session_factory) as session:
                handler(session, ctx)
        except Exception:
            logger.error(
                "Tâche planifiée en échec pour une entreprise",
                extra={"job": job, "company_id": str(company_id)},
                exc_info=True,
            )
            continue
        done += 1
    return done


def each_company(session_factory: sessionmaker[Any] | None = None) -> Iterator[UUID]:
    """Itère les entreprises, pour les tâches qui enfilent une sous-tâche par tenant."""
    yield from active_company_ids(session_factory)
