"""Façade de services du module Platform (ADR 0089).

Connexion de l'équipe CoGes, métadonnées des entreprises, suspension. Les règles de
la connexion commerçante s'appliquent à l'identique :

* e-mail inconnu, mot de passe faux et compte désactivé répondent **pareil** ;
* le mot de passe est toujours vérifié, contre un leurre si le compte n'existe pas ;
* freinage par compte avant Argon2 (ADR 0078, 0088), jamais de verrou définitif ; au
  10ᵉ échec, l'équipe est prévenue par e-mail (`COGES_PLATFORM_ALERT_EMAIL`) ;
* refresh opaque, rotatif, famille révoquée à la réutilisation, 30 s de grâce (ADR 0051).

Toutes les transactions passent par `platform_transaction` : rôle `coges_app_platform`,
jamais `coges_app`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core import queue, rate_limit
from app.core.config import get_settings
from app.core.deps import PlatformAdmin, platform_transaction
from app.core.errors import AuthenticationRequiredError, NotFoundError
from app.core.search import normalise_term
from app.core.security import (
    create_platform_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.core.tenancy import on_commit
from app.modules.platform.models import PlatformAuditLog, PlatformAuthSession, PlatformUser
from app.modules.platform.repository import (
    CompanyDirectory,
    CompanyRow,
    PlatformAuditRepository,
    PlatformSessionRepository,
    PlatformUserRepository,
)
from app.modules.platform.schemas import (
    CompanyDetail,
    CompanyPage,
    CompanySummary,
    CompanyUser,
    PlatformMe,
)

_DECOY_HASH = hash_password("leurre-de-l-administration-sans-usage")
_INVALID_CREDENTIALS = "Identifiants invalides."

#: Portée du freinage. Un slug d'entreprise ne contient jamais « : » : aucun compteur
#: de l'administration ne peut se confondre avec celui d'un commerçant.
THROTTLE_SCOPE = "platform:"

#: Tâches du worker (`app/workers/tasks/platform.py`), désignées par leur nom.
LOGIN_FAILURES_TASK = "platform.login_failures"
STATUS_CHANGED_TASK = "platform.company_status_changed"

ROTATION_GRACE = timedelta(seconds=30)

MIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True, slots=True)
class IssuedPlatformTokens:
    access_token: str
    expires_in: int
    refresh_token: str


def _audit(
    session: Session,
    *,
    actor_id: UUID | None,
    action: str,
    entity_table: str,
    entity_id: UUID | None,
    target_company_id: UUID | None = None,
    diff: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Journal critique de la plateforme, dans la transaction du geste."""
    PlatformAuditRepository(session).add(
        PlatformAuditLog(
            actor_id=actor_id,
            action=action,
            entity_table=entity_table,
            entity_id=entity_id,
            target_company_id=target_company_id,
            diff=diff,
            ip_address=ip_address,
        )
    )


def _issue_session(
    session: Session,
    *,
    platform_user_id: UUID,
    family_id: UUID,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[PlatformAuthSession, str]:
    raw_token, token_hash = generate_refresh_token()
    auth_session = PlatformSessionRepository(session).add(
        PlatformAuthSession(
            platform_user_id=platform_user_id,
            token_hash=token_hash,
            family_id=family_id,
            issued_at=datetime.now(UTC),
            expires_at=refresh_token_expiry(),
            user_agent=user_agent,
            ip_address=ip_address,
        )
    )
    return auth_session, raw_token


# ------------------------------------------------------------------- connexion


def login(
    email: str, password: str, *, user_agent: str | None = None, ip_address: str | None = None
) -> IssuedPlatformTokens:
    key = email.strip().lower()
    with platform_transaction() as session:
        user = PlatformUserRepository(session).get_by_email(key)
        found = (user.id, user.password_hash, user.is_active) if user else None

    attempt = rate_limit.begin_attempt(
        THROTTLE_SCOPE, user_id=found[0] if found else None, typed=key
    )
    password_matches = verify_password(password, found[1] if found else _DECOY_HASH)

    if found is None or not password_matches or not found[2]:
        failure = rate_limit.record_failure(attempt)
        # Une seule alerte, au seuil exact : l'attente qui suit borne déjà la cadence.
        if found is not None and failure.failures == get_settings().login_throttle_alert_after:
            queue.enqueue(
                LOGIN_FAILURES_TASK,
                countdown=0,
                platform_user_id=str(found[0]),
                failures=failure.failures,
            )
        raise AuthenticationRequiredError(_INVALID_CREDENTIALS)

    rate_limit.reset_account(attempt)
    platform_user_id = found[0]
    with platform_transaction() as session:
        user = PlatformUserRepository(session).get(platform_user_id)
        if user is None or not user.is_active:  # désactivé entre les deux transactions
            raise AuthenticationRequiredError(_INVALID_CREDENTIALS)
        user.last_login_at = datetime.now(UTC)
        _, raw_token = _issue_session(
            session,
            platform_user_id=user.id,
            family_id=uuid4(),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        _audit(
            session,
            actor_id=user.id,
            action="login",
            entity_table="platform_users",
            entity_id=user.id,
            ip_address=ip_address,
        )
        access_token, expires_in = create_platform_access_token(user.id, user.role)

    return IssuedPlatformTokens(
        access_token=access_token, expires_in=expires_in, refresh_token=raw_token
    )


def _unreceived_successor(
    repository: PlatformSessionRepository, current: PlatformAuthSession, now: datetime
) -> PlatformAuthSession | None:
    """Successeur d'un jeton tourné il y a moins de 30 s et jamais servi (ADR 0051)."""
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
) -> IssuedPlatformTokens:
    """Rotation dans une transaction, ligne verrouillée ; la réutilisation révoque la
    famille et l'erreur n'est levée qu'après le COMMIT de cette révocation."""
    reuse_detected = False
    refused = False
    issued: IssuedPlatformTokens | None = None

    with platform_transaction() as session:
        repository = PlatformSessionRepository(session)
        current = repository.lock_by_token_hash(hash_refresh_token(raw_token))
        if current is None:
            raise AuthenticationRequiredError("Jeton de rafraîchissement invalide.")

        now = datetime.now(UTC)
        successor = _unreceived_successor(repository, current, now)
        user = PlatformUserRepository(session).get(current.platform_user_id)
        if current.revoked_at is not None and successor is None:
            revoked = repository.revoke_family(current.family_id)
            _audit(
                session,
                actor_id=current.platform_user_id,
                action="cancel",
                entity_table="platform_auth_sessions",
                entity_id=current.id,
                diff={"reason": "token_reuse_detected", "revoked_sessions": revoked},
                ip_address=ip_address,
            )
            reuse_detected = True
        elif current.expires_at <= now or user is None or not user.is_active:
            refused = True
        else:
            rotated, new_raw_token = _issue_session(
                session,
                platform_user_id=user.id,
                family_id=current.family_id,
                user_agent=user_agent,
                ip_address=ip_address,
            )
            if successor is not None:
                successor.revoked_at = now
            else:
                current.revoked_at = now
                current.replaced_by = rotated.id
            access_token, expires_in = create_platform_access_token(user.id, user.role)
            issued = IssuedPlatformTokens(
                access_token=access_token, expires_in=expires_in, refresh_token=new_raw_token
            )

    if reuse_detected:
        raise AuthenticationRequiredError("Session révoquée.")
    if refused or issued is None:
        raise AuthenticationRequiredError("Session expirée.")
    return issued


def logout(raw_token: str) -> None:
    """Révoque la famille ; un jeton inconnu est sans effet et sans erreur."""
    with platform_transaction() as session:
        repository = PlatformSessionRepository(session)
        current = repository.get_by_token_hash(hash_refresh_token(raw_token))
        if current is not None:
            repository.revoke_family(current.family_id)


def me(session: Session, admin: PlatformAdmin) -> PlatformMe:
    user = PlatformUserRepository(session).get(admin.platform_user_id)
    if user is None:
        raise AuthenticationRequiredError("Session invalide.")
    return PlatformMe(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


# ------------------------------------------------------------------ entreprises


def _summary(row: CompanyRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "slug": row.slug,
        "status": row.status,
        "created_at": row.created_at,
        "user_count": row.user_count,
        "last_activity_at": row.last_activity_at,
    }


def list_companies(
    session: Session, *, search: str | None, page: int, page_size: int
) -> CompanyPage:
    rows, total = CompanyDirectory(session).search(
        search=normalise_term(search), page=page, page_size=page_size
    )
    return CompanyPage(
        items=[CompanySummary(**_summary(row)) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


def get_company(session: Session, company_id: UUID) -> CompanyDetail:
    directory = CompanyDirectory(session)
    row = directory.get(company_id)
    if row is None:
        raise NotFoundError("Entreprise introuvable.")
    return CompanyDetail(
        **_summary(row),
        users=[
            CompanyUser(
                id=user.id,
                full_name=user.full_name,
                roles=user.roles,
                is_active=user.is_active,
                last_login_at=user.last_login_at,
            )
            for user in directory.users(company_id)
        ],
    )


def set_company_status(
    session: Session,
    admin: PlatformAdmin,
    company_id: UUID,
    *,
    status: str,
    reason: str,
    ip_address: str | None = None,
) -> CompanyDetail:
    """Suspend ou réactive une entreprise (`active` ↔ `suspended`).

    Audit critique dans la même transaction ; le gérant est prévenu par e-mail **après**
    le COMMIT. Redemander le statut déjà en place ne change rien et ne prévient personne.
    """
    directory = CompanyDirectory(session)
    before = directory.lock_status(company_id)
    if before is None:
        raise NotFoundError("Entreprise introuvable.")
    if before != status:
        directory.set_status(company_id, status)
        _audit(
            session,
            actor_id=admin.platform_user_id,
            action="update",
            entity_table="companies",
            entity_id=company_id,
            target_company_id=company_id,
            diff={"before": {"status": before}, "after": {"status": status}, "reason": reason},
            ip_address=ip_address,
        )

        def _notify_manager() -> None:
            queue.enqueue(
                STATUS_CHANGED_TASK, countdown=0, company_id=str(company_id), status=status
            )

        on_commit(session, _notify_manager)
    return get_company(session, company_id)


# -------------------------------------------------------------------------- CLI


def create_platform_user(*, email: str, display_name: str, role: str, password: str) -> UUID:
    """Crée un compte de l'équipe. Réservé à la CLI : aucune route d'inscription."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Le mot de passe doit faire au moins {MIN_PASSWORD_LENGTH} caractères.")
    if role not in ("administrator", "support"):
        raise ValueError("Profil inconnu : administrator ou support.")
    with platform_transaction() as session:
        user = PlatformUserRepository(session).add(
            PlatformUser(
                email=email.strip().lower(),
                password_hash=hash_password(password),
                display_name=display_name.strip(),
                role=role,
            )
        )
        _audit(
            session,
            actor_id=None,
            action="insert",
            entity_table="platform_users",
            entity_id=user.id,
            diff={"after": {"role": role}},
        )
        return user.id


def deactivate_platform_user(*, email: str) -> bool:
    """Coupe un compte de l'équipe (CLI) ; ses sessions tombent par trigger. `False` :
    aucun compte actif à cette adresse."""
    with platform_transaction() as session:
        user = PlatformUserRepository(session).get_by_email(email.strip().lower())
        if user is None or not user.is_active:
            return False
        user.is_active = False
        _audit(
            session,
            actor_id=None,
            action="update",
            entity_table="platform_users",
            entity_id=user.id,
            diff={"before": {"is_active": True}, "after": {"is_active": False}},
        )
        return True
