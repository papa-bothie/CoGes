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

import secrets
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import (
    AuthenticationRequiredError,
    NotFoundError,
    PasswordChangeRequiredError,
    PermissionDeniedError,
)
from app.core.observability import tag_tenant
from app.core.security import AccessClaims, decode_access_token
from app.core.tenancy import TenantContext, tenant_transaction

_LOAD_IDENTITY = text(
    """
    SELECT u.company_id AS company_id,
           u.is_active  AS is_active,
           u.must_change_password AS must_change_password,
           COALESCE(
             array_agg(p.code) FILTER (WHERE p.code IS NOT NULL),
             ARRAY[]::text[]
           ) AS permissions
    FROM users u
    -- Une entreprise supprimée ferme toutes ses sessions, jetons encore valides compris
    -- (lot C, ADR 0086) : la connexion le vérifiait déjà, la relecture aussi désormais.
    JOIN companies c ON c.id = u.company_id AND c.deleted_at IS NULL
    LEFT JOIN user_roles       ur ON ur.company_id = u.company_id AND ur.user_id = u.id
    LEFT JOIN role_permissions rp ON rp.company_id = u.company_id AND rp.role_id = ur.role_id
    LEFT JOIN permissions       p ON p.id = rp.permission_id
    WHERE u.id = :user_id
      AND u.deleted_at IS NULL
    GROUP BY u.company_id, u.is_active, u.must_change_password
    """
)

#: Les seules routes ouvertes à un compte qui doit changer son mot de passe (ADR 0074).
PASSWORD_CHANGE_PATHS = frozenset({"/api/v1/auth/me", "/api/v1/auth/password"})


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
            # Utilisateur inexistant, supprimé, rattaché à une autre entreprise, ou
            # entreprise supprimée : indiscernable d'un jeton invalide.
            raise AuthenticationRequiredError("Session invalide.")
        if not row.is_active:
            raise AuthenticationRequiredError("Ce compte est désactivé.")
        if row.must_change_password and request.url.path not in PASSWORD_CHANGE_PATHS:
            raise PasswordChangeRequiredError()

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
        # Compteur par entreprise (décision 16), sur le `company_id` relu en base.
        rate_limit.hit_tenant(company_id)
        tag_tenant(company_id)
        yield TenantSession(session=session, ctx=ctx)


#: Portée `function` (ADR 0079) : la transaction est validée à la sortie du handler,
#: **avant** l'envoi de la réponse. En portée `request` (défaut de FastAPI), le COMMIT
#: aurait lieu après l'envoi, et un COMMIT refusé laisserait au client un 2xx menteur.
CurrentTenant = Annotated[TenantSession, Depends(get_tenant_session, scope="function")]


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


def require_ops_token(request: Request) -> None:
    """Exige le jeton d'exploitation `COGES_OPS_TOKEN` (ADR 0077).

    Aucun utilisateur, aucune entreprise : c'est l'exploitant qui interroge, depuis
    un terminal ou un service de surveillance. Comparaison en temps constant. Sans
    jeton configuré, la route n'existe pas (404) : rien à deviner.
    """
    configured = get_settings().ops_token
    expected = configured.get_secret_value() if configured else ""
    if not expected:
        raise NotFoundError()
    scheme, _, presented = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        presented.strip().encode(), expected.encode()
    ):
        raise AuthenticationRequiredError("Jeton d'exploitation absent ou invalide.")


def get_platform_session() -> Iterator[Session]:  # à prendre en portée `function`
    """Transaction sans entreprise, pour les lectures de plate-forme (ADR 0077).

    Le contexte est l'entreprise nulle : la RLS ne laisse rien voir de métier. Seules
    les fonctions `SECURITY DEFINER` qui rendent des agrégats sans identifiant
    (`outbox_lag`, `job_runs_latest`) ont quelque chose à dire ici.
    """
    with tenant_transaction(TenantContext.bootstrap(UUID(int=0))) as session:
        yield session


def client_ip(request: Request) -> str | None:
    """Adresse IP de l'appelant, pour l'audit et les sessions.

    La valeur est **validée** avant d'être renvoyée : `audit_logs.ip_address` et
    `auth_sessions.ip_address` sont de type `inet`, et une valeur non conforme —
    un client de test, un proxy mal configuré — ferait échouer l'INSERT, donc
    toute la transaction métier. Une adresse inexploitable vaut mieux absente.
    """
    return parse_ip(raw_client_ip(request.headers.get("x-forwarded-for"), request.client))


def raw_client_ip(forwarded_for: str | None, client: object | None) -> str | None:
    """Adresse brute : `X-Forwarded-For` derrière Caddy, sinon le pair TCP.

    L'en-tête n'est lu que si `trust_proxy_headers` est actif : en dehors d'un proxy
    qui le réécrit, n'importe quel client pourrait choisir son adresse, donc son
    compteur de limitation de débit. On garde l'entrée **la plus à droite**, celle
    qu'écrit notre propre proxy (ADR 0083) : les précédentes viennent du client, qui
    peut envoyer son propre `X-Forwarded-For` pour se faire passer pour un autre.
    """
    if forwarded_for and get_settings().trust_proxy_headers:
        return forwarded_for.rsplit(",", 1)[-1].strip()
    return getattr(client, "host", None)


def parse_ip(value: str | None) -> str | None:
    """Adresse validée, ou `None` si elle est inexploitable."""
    if value is None:
        return None
    try:
        return str(ip_address(value))
    except ValueError:
        return None
