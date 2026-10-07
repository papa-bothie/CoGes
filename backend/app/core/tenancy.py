"""Contexte tenant et **unique** point d'entrée transactionnel.

C'est le seul module du projet autorisé à poser `app.company_id`. Un test
d'architecture (`tests/architecture/test_tenant_context_is_unique.py`) échoue si un
autre fichier y touche.

Chaîne d'isolation (Diagramme 8) :

1. le `company_id` vient du serveur (JWT → utilisateur en base), jamais du client ;
2. `set_config('app.company_id', :id, true)` — le `true` signifie « portée
   transaction », c'est l'équivalent exact de `SET LOCAL`, mais l'UUID passe en
   paramètre lié, donc sans concaténation de chaîne ;
3. assertion immédiate : la base doit confirmer la valeur posée ;
4. COMMIT ou ROLLBACK : le contexte meurt avec la transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import text

from app.core.database import get_session_factory
from app.core.errors import TenantContextError

logger = logging.getLogger(__name__)

#: Clé de `Session.info` où s'empilent les rappels à jouer après COMMIT.
_AFTER_COMMIT = "coges_after_commit"

# Portée transaction (`is_local = true`) : strictement équivalent à SET LOCAL.
# Publiques à dessein : le test T4 les rejoue telles quelles, pour qu'un jour où
# quelqu'un passerait la portée à `false`, le test échoue au lieu de se taire.
SET_TENANT_CONTEXT_SQL = text("SELECT set_config('app.company_id', :company_id, true)")
READ_TENANT_CONTEXT_SQL = text("SELECT current_setting('app.company_id', true)")

#: Acteur « inconnu » des contextes d'amorçage. N'est jamais un utilisateur réel :
#: `users.id` est un uuid aléatoire, jamais le zéro.
NIL_USER_ID = UUID(int=0)


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Identité résolue côté serveur. Immuable : on ne change pas de tenant en cours de route."""

    user_id: UUID
    company_id: UUID
    permissions: frozenset[str] = field(default_factory=frozenset)

    def has_permission(self, code: str) -> bool:
        """Vérification RBAC côté serveur (le front ne fait que masquer)."""
        return code in self.permissions

    @classmethod
    def bootstrap(cls, company_id: UUID) -> TenantContext:
        """Contexte sans utilisateur identifié, pour les rares amorçages.

        Deux cas seulement : la **création d'une entreprise** (l'UUID est
        pré-généré, aucun utilisateur n'existe encore) et le **rafraîchissement
        d'un jeton** (le porteur n'est connu qu'après lecture de la session).
        Aucune permission n'est accordée : toute route protégée refuserait ce
        contexte.
        """
        return cls(user_id=NIL_USER_ID, company_id=company_id)


@contextmanager
def tenant_transaction(
    ctx: TenantContext, *, session_factory: sessionmaker[Any] | None = None
) -> Iterator[Session]:
    """Ouvre une transaction, y pose le contexte tenant, puis commit ou rollback.

    Aucune requête métier ne doit s'exécuter hors de ce gestionnaire.
    """
    factory = session_factory or get_session_factory()
    session: Session = factory()
    try:
        with session.begin():
            session.execute(SET_TENANT_CONTEXT_SQL, {"company_id": str(ctx.company_id)})
            observed = session.execute(READ_TENANT_CONTEXT_SQL).scalar_one()
            if observed != str(ctx.company_id):
                # Contexte non pris en compte : on refuse d'exécuter quoi que ce soit.
                raise TenantContextError(
                    "Le contexte d'entreprise n'a pas été appliqué par la base.",
                    details={"expected": str(ctx.company_id), "observed": observed},
                )
            yield session
        # Atteint seulement si le COMMIT a réussi : une exception sortie du bloc
        # ci-dessus a déjà fait le ROLLBACK et ne passe pas par ici.
        _run_after_commit(session)
    finally:
        session.close()


def on_commit(session: Session, callback: Callable[[], None]) -> None:
    """Joue `callback` une fois la transaction de `session` **validée**.

    Sert aux effets hors base qui ne doivent jamais précéder le COMMIT, comme vider
    un cache (ADR 0061) : vidé avant, il pourrait être rempli à nouveau par une
    lecture qui ne voit pas encore l'écriture. Après un ROLLBACK, rien n'est joué.
    """
    session.info.setdefault(_AFTER_COMMIT, []).append(callback)


def _run_after_commit(session: Session) -> None:
    """Rappels après COMMIT : un échec est journalisé, jamais propagé.

    La transaction est validée ; faire échouer la requête maintenant ferait croire au
    client que son écriture n'a pas eu lieu.
    """
    callbacks: list[Callable[[], None]] = session.info.pop(_AFTER_COMMIT, [])
    for callback in callbacks:
        try:
            callback()
        except Exception:
            logger.exception("Rappel après COMMIT en échec")
