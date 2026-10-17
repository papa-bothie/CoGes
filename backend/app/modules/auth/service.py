"""Façade de services du module Auth.

Connexion par le couple (slug d'entreprise, e-mail), jetons courts, refresh
**rotatif** avec détection de réutilisation (décision 16).

Quatre règles de non-divulgation :

* slug inconnu, e-mail inconnu, mot de passe faux et compte désactivé renvoient
  **exactement** le même message et le même statut ;
* le freinage par compte (ADR 0078) compte ce qui a été **tapé**, que le compte existe
  ou non, et répond pareil dans les deux cas ;
* l'échéance d'un mot de passe provisoire ne se révèle qu'**après** le mot de passe
  vérifié : seul qui le connaît apprend qu'il a expiré ;
* un mot de passe est toujours vérifié, même sans identité trouvée, pour ne pas
  créer d'oracle temporel ;
* la connexion réussie relève de l'audit **asynchrone**, pas du canal critique.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core import queue, rate_limit
from app.core.audit import AuditAction, audit_critical
from app.core.config import get_settings
from app.core.errors import AuthenticationRequiredError, TemporaryPasswordExpiredError
from app.core.phone import normalise_phone
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
    AuthIdentity,
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

#: Tâche du worker qui écrit l'alerte d'échecs répétés (`app/workers/tasks/notifications.py`).
LOGIN_FAILURES_TASK = "notifications.login_failures"


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
    """Authentifie un couple (slug, e-mail ou téléphone) et ouvre une famille de sessions.

    Un identifiant sans « @ » est un numéro, ramené à ses chiffres (ADR 0074). Un
    numéro illisible ne cherche personne, mais le mot de passe est vérifié quand même
    contre le leurre : la réponse ne trahit pas la forme de l'identifiant.
    """
    raw = payload.login_identifier
    key = raw.lower() if "@" in raw else normalise_phone(raw)
    # Le compteur suit ce qui a été tapé, ramené à la même forme que la recherche.
    throttle_id = key or raw.strip().lower()
    rate_limit.check_account(payload.company_slug, throttle_id)

    identity = None
    if key:
        with auth_lookup_transaction() as lookup_session:
            identity = lookup_identity(lookup_session, slug=payload.company_slug, email=key)

    password_hash = identity.password_hash if identity else _DECOY_HASH
    password_matches = verify_password(payload.password, password_hash)

    if identity is None or not password_matches or not identity.is_active:
        failure = rate_limit.record_account_failure(payload.company_slug, throttle_id)
        if identity is not None and failure.failures >= get_settings().login_throttle_alert_after:
            _alert_repeated_failures(identity, failure.failures)
        raise AuthenticationRequiredError(_INVALID_CREDENTIALS)

    if _temporary_password_expired(identity):
        # Ni échec ni succès pour le freinage : le mot de passe tapé était le bon.
        _audit_expired_temporary_password(identity, ip_address)
        raise TemporaryPasswordExpiredError()

    rate_limit.reset_account(payload.company_slug, throttle_id)

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


def _temporary_password_expired(identity: AuthIdentity) -> bool:
    """Heure réelle, jamais `app.core.clock` : une échéance de sécurité, comme un jeton."""
    deadline = identity.must_change_password_until
    return identity.must_change_password and deadline is not None and deadline <= datetime.now(UTC)


def _audit_expired_temporary_password(identity: AuthIdentity, ip_address: str | None) -> None:
    """Trace la tentative refusée, dans sa propre transaction validée avant le refus."""
    ctx = TenantContext(user_id=identity.user_id, company_id=identity.company_id)
    with tenant_transaction(ctx) as session:
        audit_critical(
            session,
            ctx,
            action=AuditAction.LOGIN,
            entity_table="users",
            entity_id=identity.user_id,
            before={"must_change_password_until": _iso(identity.must_change_password_until)},
            after={"refused": "temporary_password_expired"},
            ip_address=ip_address,
        )


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def _alert_repeated_failures(identity: AuthIdentity, failures: int) -> None:
    """Demande au worker de prévenir qui gère les personnes (ADR 0078).

    Auth est de la Plateforme, les alertes de la Restitution : la tâche est désignée
    par son nom, et c'est le worker qui écrit l'alerte. Si Redis manque, l'alerte se
    perd, le freinage, lui, tient.
    """
    queue.enqueue(
        LOGIN_FAILURES_TASK,
        countdown=0,
        company_id=str(identity.company_id),
        user_id=str(identity.user_id),
        failures=failures,
    )


#: Fenêtre pendant laquelle un jeton déjà tourné peut être représenté sans être pris
#: pour un vol (ADR 0051) : la réponse de rotation s'est perdue (navigation, coupure).
ROTATION_GRACE = timedelta(seconds=30)


def _unreceived_successor(
    repository: AuthSessionRepository, current: AuthSession, now: datetime
) -> AuthSession | None:
    """Successeur d'un jeton tourné **il y a moins de 30 s** et qui n'a jamais servi.

    C'est la signature d'une réponse perdue : le client représente l'ancien jeton parce
    qu'il n'a jamais reçu le nouveau. Rien n'est rendu — donc réutilisation — si le
    jeton a été révoqué autrement que par une rotation (déconnexion, famille révoquée),
    si la fenêtre est passée, ou si le successeur a déjà servi ou expiré.
    """
    if current.revoked_at is None or current.replaced_by is None:
        return None
    if now - current.revoked_at > ROTATION_GRACE:
        return None
    successor = repository.lock_by_id(current.replaced_by)
    if successor is None or successor.revoked_at is not None or successor.expires_at <= now:
        return None
    return successor


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
        successor = _unreceived_successor(repository, current, now)
        if current.revoked_at is not None and successor is None:
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

            if successor is not None:
                # Réponse de rotation perdue (ADR 0051) : le successeur n'a jamais été
                # reçu, il est écarté ; la famille reste vivante et c'est tracé. Il
                # n'a pas de `replaced_by` : présenté à son tour, il ne bénéficie
                # d'aucune grâce — une seule reprise par rotation.
                successor.revoked_at = now
                audit_critical(
                    session,
                    user_ctx,
                    action=AuditAction.UPDATE,
                    entity_table="auth_sessions",
                    entity_id=current.id,
                    before={
                        "family_id": str(current.family_id),
                        "reason": "rotation_retried_within_grace",
                        "unreceived_session_id": str(successor.id),
                    },
                    after={"session_id": str(rotated.id)},
                    ip_address=ip_address,
                )
            else:
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
        user=MeUser(
            id=user.id,
            email=user.email,
            phone=user.phone,
            full_name=user.full_name,
            must_change_password=user.must_change_password,
        ),
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
            receipt_format=companies_service.receipt_format(session, ctx),
        ),
    )
