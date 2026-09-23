"""Dépendances FastAPI : du jeton au contexte tenant.

Chaîne du Diagramme 8, étape 1 :

1. le jeton d'accès est **vérifié** (signature et expiration) ;
2. une transaction s'ouvre sur le `company_id` porté par le jeton ;
3. l'utilisateur est **relu en base** dans cette transaction. La RLS ne renvoie la
   ligne que si le couple (utilisateur, entreprise) existe réellement : un jeton dont
   le `company_id` ne correspond pas à l'utilisateur ne ramène rien, et la requête
   échoue en 401 ;
4. le `TenantContext` est construit à partir de **la ligne lue**, pas du claim.

Il n'existe aucun chemin où le `company_id` viendrait d'un en-tête, d'un paramètre
de requête ou du corps.

Les lectures d'identité sont écrites ici en SQL, sans passer par un module : la
détermination du tenant est une brique de plate-forme, et `core/` ne doit jamais
dépendre de `modules/` (dépendances vers le bas uniquement).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from app.core.errors import AuthenticationRequiredError, PermissionDeniedError
from app.core.security import AccessClaims, decode_access_token
from app.core.tenancy import TenantContext, tenant_transaction

_LOAD_IDENTITY = text(
    """
    SELECT u.company_id AS company_id,
           u.is_active  AS is_active,
           COALESCE(
             array_agg(p.code) FILTER (WHERE p.code IS NOT NULL),
             ARRAY[]::text[]
           ) AS permissions
    FROM users u
    LEFT JOIN user_roles       ur ON ur.company_id = u.company_id AND ur.user_id = u.id
    LEFT JOIN role_permissions rp ON rp.company_id = u.company_id AND rp.role_id = ur.role_id
    LEFT JOIN permissions       p ON p.id = rp.permission_id
    WHERE u.id = :user_id
      AND u.deleted_at IS NULL
    GROUP BY u.company_id, u.is_active
    """
)


@dataclass(frozen=True, slots=True)
class TenantSession:
    """Session déjà placée dans une transaction, avec son contexte tenant."""

    session: Session
    ctx: TenantContext


def get_access_claims(request: Request) -> AccessClaims:
    """Extrait et vérifie le jeton d'accès de l'en-tête `Authorization`."""
    header = request.headers.get("authorization")
    if not header or not header.lower().startswith("bearer "):
        raise AuthenticationRequiredError("Jeton d'accès absent.")
    return decode_access_token(header.split(" ", 1)[1].strip())


def get_tenant_session(
    request: Request, claims: Annotated[AccessClaims, Depends(get_access_claims)]
) -> Iterator[TenantSession]:
    """Ouvre la transaction du cas d'usage et y construit le contexte tenant."""
    # Contexte provisoire : il ne sert qu'à autoriser la relecture de l'utilisateur.
    provisional = TenantContext(user_id=claims.user_id, company_id=claims.company_id)

    with tenant_transaction(provisional) as session:
        row = session.execute(_LOAD_IDENTITY, {"user_id": claims.user_id}).one_or_none()
        if row is None:
            # Utilisateur inexistant, supprimé, ou rattaché à une autre entreprise :
            # la RLS a filtré la ligne. Indiscernable d'un jeton invalide.
            raise AuthenticationRequiredError("Session invalide.")
        if not row.is_active:
            raise AuthenticationRequiredError("Ce compte est désactivé.")

        company_id: UUID = row.company_id
        ctx = TenantContext(
            user_id=claims.user_id,
            company_id=company_id,
            permissions=frozenset(row.permissions),
        )
        # Le contexte de journalisation est posé par le middleware, jamais ici :
        # FastAPI exécute la mise en place et la fermeture d'une dépendance
        # synchrone dans deux `Context` différents, et un `ContextVar.reset()` y
        # lèverait `ValueError`, ce qui ferait tomber la transaction du cas d'usage.
        request.state.tenant = ctx
        yield TenantSession(session=session, ctx=ctx)


CurrentTenant = Annotated[TenantSession, Depends(get_tenant_session)]


def require_permission(code: str) -> Callable[[TenantSession], TenantSession]:
    """Exige une permission, **côté serveur**. Le front ne fait que masquer.

    Un droit manquant dans sa propre entreprise donne 403. Une ressource appartenant
    à une autre entreprise donne 404, jamais 403 : un 403 révélerait son existence.
    """

    def dependency(tenant: CurrentTenant) -> TenantSession:
        if not tenant.ctx.has_permission(code):
            raise PermissionDeniedError(
                "Vous n'avez pas la permission d'effectuer cette action.",
                details={"required_permission": code},
            )
        return tenant

    return dependency


def client_ip(request: Request) -> str | None:
    """Adresse IP de l'appelant, pour l'audit et les sessions.

    La valeur est **validée** avant d'être renvoyée : `audit_logs.ip_address` et
    `auth_sessions.ip_address` sont de type `inet`, et une valeur non conforme —
    un client de test, un proxy mal configuré — ferait échouer l'INSERT, donc
    toute la transaction métier. Une adresse inexploitable vaut mieux absente.
    """
    if request.client is None:
        return None
    try:
        return str(ip_address(request.client.host))
    except ValueError:
        return None
