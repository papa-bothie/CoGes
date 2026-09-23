"""Dépendances FastAPI — squelette.

Le `company_id` vient **du serveur** : JWT vérifié → utilisateur chargé en base →
`company_id` lu sur son rattachement. Il n'existe et n'existera **aucun** chemin où
il viendrait d'un en-tête, d'un paramètre de requête ou du corps.

La résolution réelle est branchée en phase 02 (authentification). En attendant,
toute route protégée répond 401 : aucun mode dégradé, aucun contexte par défaut.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.core.errors import AuthenticationRequiredError
from app.core.tenancy import TenantContext, tenant_transaction


def get_tenant_context() -> TenantContext:
    """Contexte tenant de la requête courante.

    Branché sur l'authentification en phase 02.
    """
    raise AuthenticationRequiredError(
        "L'authentification sera disponible en phase 02.",
    )


def get_tenant_session() -> Iterator[Session]:
    """Session déjà placée dans une transaction avec le contexte tenant posé."""
    ctx = get_tenant_context()
    with tenant_transaction(ctx) as session:
        yield session
