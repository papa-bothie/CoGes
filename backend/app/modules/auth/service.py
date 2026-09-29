"""Façade de services du module Auth.

Connexion par le couple (slug d'entreprise, e-mail), jetons courts, refresh
**rotatif** avec détection de réutilisation (décision 16).

Trois règles de non-divulgation :

* slug inconnu, e-mail inconnu, mot de passe faux et compte désactivé renvoient
  **exactement** le même message et le même statut ;
* un mot de passe est toujours vérifié, même sans identité trouvée, pour ne pas
  créer d'oracle temporel ;
* la connexion réussie relève de l'audit **asynchrone**, pas du canal critique.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import AuthenticationRequiredError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.auth.models import AuthSession
from app.modules.auth.repository import (
    AuthSessionRepository,
    auth_lookup_transaction,
    lookup_identity,
)
from app.modules.auth.schemas import LoginRequest, MeCompany, MeResponse, MeRole, MeUser
from app.modules.companies import service as companies_service
from app.modules.rbac import service as rbac_service
from app.modules.users import service as users_service

#: Haché une fois au chargement : sert de leurre quand aucune identité n'est trouvée,
#: pour que la durée de la réponse ne trahisse pas l'existence d'un compte.
_DECOY_HASH = hash_password("mot-de-passe-leurre-sans-usage")

_INVALID_CREDENTIALS = "Identifiants invalides."


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    """Jetons émis par une connexion ou un rafraîchissement."""

    access_token: str
    expires_in: int
    refresh_token: str
    company_id: UUID
    user_id: UUID


def _compose_refresh_token(company_id: UUID, secret: str) -> str:
    """Le refresh token porte son `company_id` en clair.

    Ce n'est pas un secret — le porteur connaît déjà son entreprise — et cela évite
    une seconde fonction capable de franchir la RLS pour retrouver la session.
    """
    return f"{company_id}.{secret}"


def _split_refresh_token(raw_token: str) -> tuple[UUID, str]:
    company_part, separator, _ = raw_token.partition(".")
    if not separator:
        raise AuthenticationRequiredError("Jeton de rafraîchissement invalide.")
    try:
        return UUID(company_part), raw_token
    except ValueError as exc:
        raise AuthenticationRequiredError("Jeton de rafraîchissement invalide.") from exc


def _issue_session(
    ctx: TenantContext,
    session_repository: AuthSessionRepository,
    *,
    user_id: UUID,
    family_id: UUID,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[AuthSession, str]:
    """Crée une ligne `auth_sessions` et renvoie le jeton en clair."""
    secret, _ = generate_refresh_token()
    raw_token = _compose_refresh_token(ctx.company_id, secret)
    auth_session = session_repository.add(
        AuthSession(
            company_id=ctx.company_id,
            user_id=user_id,
            token_hash=hash_refresh_token(raw_token),
            family_id=family_id,
            issued_at=datetime.now(UTC),
            expires_at=refresh_token_expiry(),
            user_agent=user_agent,
            ip_address=ip_address,
        )
    )
    return auth_session, raw_token


def login(
    payload: LoginRequest, *, user_agent: str | None = None, ip_address: str | None = None
) -> IssuedTokens:
    """Authentifie un couple (slug, e-mail) et ouvre une famille de sessions."""
    with auth_lookup_transaction() as lookup_session:
        identity = lookup_identity(
            lookup_session, slug=payload.company_slug, email=str(payload.email)
        )

    password_hash = identity.password_hash if identity else _DECOY_HASH
    password_matches = verify_password(payload.password, password_hash)

    if identity is None or not password_matches or not identity.is_active:
        raise AuthenticationRequiredError(_INVALID_CREDENTIALS)

    ctx = TenantContext(user_id=identity.user_id, company_id=identity.company_id)
    with tenant_transaction(ctx) as session:
        user = users_service.get_user(session, ctx, identity.user_id)
        users_service.record_login(session, user)
        _, raw_token = _issue_session(
            ctx,
            AuthSessionRepository(session, ctx),
            user_id=identity.user_id,
            family_id=uuid4(),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        access_token, expires_in = create_access_token(identity.user_id, identity.company_id)

    return IssuedTokens(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=raw_token,
        company_id=identity.company_id,
        user_id=identity.user_id,
    )


def refresh(
    raw_token: str, *, user_agent: str | None = None, ip_address: str | None = None
) -> IssuedTokens:
    """Consomme un refresh token et en émet un nouveau dans la même famille.

    Tout se joue dans **une seule** transaction, sur une ligne verrouillée : de la
    lecture du jeton jusqu'au COMMIT, personne d'autre ne peut le consommer. Deux
    rafraîchissements concurrents avec le même jeton se sérialisent donc, et le
    second est traité comme une réutilisation.

    Rejouer un jeton déjà consommé ou révoqué est le signe d'un vol : **toute la
    famille** est révoquée, et l'incident est audité en transactionnel. L'erreur
    n'est levée qu'**après** le COMMIT — la lever à l'intérieur annulerait la
    révocation et sa ligne d'audit, c'est-à-dire exactement ce qu'il fallait garder.
    """
    company_id, token_value = _split_refresh_token(raw_token)
    ctx = TenantContext.bootstrap(company_id)

    reuse_detected = False
    expired = False
    issued: IssuedTokens | None = None

    with tenant_transaction(ctx) as session:
        repository = AuthSessionRepository(session, ctx)
        current = repository.lock_by_token_hash(hash_refresh_token(token_value))
        if current is None:
            # Rien n'a été écrit : lever ici est sans conséquence.
            raise AuthenticationRequiredError("Jeton de rafraîchissement invalide.")

        now = datetime.now(UTC)
        if current.revoked_at is not None:
            revoked = repository.revoke_family(current.family_id)
            audit_critical(
                session,
                TenantContext(user_id=current.user_id, company_id=company_id),
                action=AuditAction.CANCEL,
                entity_table="auth_sessions",
                entity_id=current.id,
                before={"family_id": str(current.family_id), "reason": "token_reuse_detected"},
                after={"revoked_sessions": revoked},
                ip_address=ip_address,
            )
            reuse_detected = True
        elif current.expires_at <= now:
            expired = True
        else:
            user_ctx = TenantContext(user_id=current.user_id, company_id=company_id)
            rotated, new_raw_token = _issue_session(
                user_ctx,
                repository,
                user_id=current.user_id,
                family_id=current.family_id,
                user_agent=user_agent,
                ip_address=ip_address,
            )
            session.flush()

            current.revoked_at = now
            current.replaced_by = rotated.id
            access_token, expires_in = create_access_token(current.user_id, company_id)
            issued = IssuedTokens(
                access_token=access_token,
                expires_in=expires_in,
                refresh_token=new_raw_token,
                company_id=company_id,
                user_id=current.user_id,
            )

    if reuse_detected:
        raise AuthenticationRequiredError("Session révoquée.")
    if expired:
        raise AuthenticationRequiredError("Session expirée.")

    assert issued is not None  # noqa: S101 - garanti par les branches ci-dessus
    return issued


def logout(raw_token: str) -> None:
    """Révoque la famille entière : se déconnecter coupe toute la chaîne de ce poste.

    Un jeton inconnu ne provoque pas d'erreur : se déconnecter deux fois est sans
    conséquence, et cela ne révèle pas si le jeton existait.
    """
    try:
        company_id, token_value = _split_refresh_token(raw_token)
    except AuthenticationRequiredError:
        return

    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx) as session:
        repository = AuthSessionRepository(session, ctx)
        current = repository.get_by_token_hash(hash_refresh_token(token_value))
        if current is not None:
            repository.revoke_family(current.family_id)


def current_identity(session: Session, ctx: TenantContext) -> MeResponse:
    """Qui est connecté, avec quels rôles, dans quelle entreprise.

    Les permissions sont celles du contexte, relues en base par la dépendance de
    session : exactement celles que les routes vérifieront.
    """
    user = users_service.get_user(session, ctx, ctx.user_id)
    company = companies_service.get_current_company(session, ctx)
    return MeResponse(
        user=MeUser(id=user.id, email=user.email, full_name=user.full_name),
        roles=[
            MeRole(
                id=role.id,
                name=role.name,
                description=role.description,
                is_system=role.is_system,
            )
            for role in rbac_service.roles_for_user(session, ctx, ctx.user_id)
        ],
        permissions=sorted(ctx.permissions),
        company=MeCompany(
            id=company.id,
            name=company.name,
            slug=company.slug,
            currency=company.currency,
            timezone=company.timezone,
            tax_enabled=companies_service.is_tax_enabled(session, ctx),
        ),
    )
