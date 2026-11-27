"""Façade de services du module Platform (ADR 0089).

Connexion de l'équipe CoGes, métadonnées des entreprises, suspension. Les règles de
la connexion commerçante s'appliquent à l'identique :

* e-mail inconnu, mot de passe faux et compte désactivé répondent **pareil** ;
* le mot de passe est toujours vérifié, contre un leurre si le compte n'existe pas ;
* freinage par compte avant Argon2 (ADR 0078, 0088), jamais de verrou définitif ; au
  10ᵉ échec, l'équipe est prévenue par e-mail (`COGES_PLATFORM_ALERT_EMAIL`) ;
* refresh opaque, rotatif, famille révoquée à la réutilisation, 30 s de grâce (ADR 0051) ;
* **double authentification obligatoire** (ADR 0105) : le mot de passe ne donne qu'un
  jeton intermédiaire ; la session s'ouvre après le code TOTP (ou un code de secours).
  Session de 12 h au plus, refusée après 1 h sans rafraîchissement.

Toutes les transactions passent par `platform_transaction` : rôle `coges_app_platform`,
jamais `coges_app`.
"""

from __future__ import annotations

import hashlib
import secrets
from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import segno
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock, mailer, mfa, plan_features, queue, rate_limit, renewal, totp
from app.core.audit import AuditAction, audit_critical
from app.core.config import DEVELOPMENT_ENVS, get_settings
from app.core.deps import PlatformAdmin, platform_transaction
from app.core.errors import (
    AuthenticationRequiredError,
    BusinessRuleError,
    CogesError,
    ConcurrentUpdateError,
    NotFoundError,
    ValidationFailedError,
    constraint_name,
)
from app.core.idempotency import IdempotencyKeyReusedError
from app.core.search import normalise_term
from app.core.security import (
    create_platform_access_token,
    create_support_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.core.tenancy import TenantContext, on_commit, tenant_transaction
from app.modules.platform import capabilities
from app.modules.platform.models import (
    Plan,
    PlatformAuditLog,
    PlatformAuthSession,
    PlatformInvitation,
    PlatformKnownDevice,
    PlatformMfaChallenge,
    PlatformUser,
    Subscription,
    SubscriptionPayment,
    SupportSession,
)
from app.modules.platform.repository import (
    AttentionRepository,
    AuditReader,
    CompanyDirectory,
    CompanyRow,
    MerchantUserDirectory,
    MfaRepository,
    PlatformAuditRepository,
    PlatformSessionRepository,
    PlatformUserRepository,
    StatsRepository,
    SubscriptionRepository,
    SupportSessionRepository,
    TeamRepository,
)
from app.modules.platform.schemas import (
    AcquiredRightsUpdate,
    AttentionRead,
    AuditEntry,
    AuditPage,
    Capability,
    CompanyDetail,
    CompanyPage,
    CompanyStatusCounts,
    CompanySummary,
    CompanyUser,
    ExpiringInvitation,
    InvitationCreate,
    InvitationIssued,
    MerchantUser,
    MerchantUserPage,
    MfaEnrollment,
    PlanBreakdown,
    PlanRead,
    PlatformMe,
    ProfileRead,
    ReminderContact,
    ReminderItem,
    ReminderList,
    RevenueRead,
    SecurityEvent,
    SignupBucket,
    SignupsRead,
    StatsGranularity,
    StatsOverview,
    StatsPeriod,
    SubscriptionDetail,
    SubscriptionExtend,
    SubscriptionPaymentCreate,
    SubscriptionPaymentRead,
    SubscriptionUpdate,
    SupportAccessToken,
    SupportSessionCreate,
    SupportSessionList,
    SupportSessionRead,
    SuspendedCompany,
    TeamInvitation,
    TeamList,
    TeamMember,
    TeamMemberUpdate,
    TeamSummary,
    TrialEnding,
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

#: Double authentification (ADR 0105).
CHALLENGE_TTL = timedelta(minutes=5)
SESSION_MAX_AGE = timedelta(hours=12)
SESSION_IDLE = timedelta(hours=1)
SECURITY_NOTICE_TASK = "platform.security_notice"
SECURITY_EVENTS_WINDOW = timedelta(days=7)

MIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True, slots=True)
class IssuedPlatformTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    #: Jeton d'appareil à (re)poser en cookie ; `None` : rien à poser.
    device_token: str | None = None
    #: Codes de secours tirés à l'activation, montrés une seule fois.
    recovery_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoginStep:
    """Mot de passe accepté : l'étape suivante et son jeton intermédiaire."""

    step: str
    challenge_token: str
    expires_in: int


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
    authenticated_at: datetime | None = None,
) -> tuple[PlatformAuthSession, str]:
    """Une session de l'administration : 12 h au plus depuis `authenticated_at` (le
    mot de passe et le code), quelle que soit la durée d'un refresh commerçant."""
    raw_token, token_hash = generate_refresh_token()
    now = datetime.now(UTC)
    started = authenticated_at or now
    auth_session = PlatformSessionRepository(session).add(
        PlatformAuthSession(
            platform_user_id=platform_user_id,
            token_hash=token_hash,
            family_id=family_id,
            issued_at=now,
            authenticated_at=started,
            expires_at=min(refresh_token_expiry(), started + SESSION_MAX_AGE),
            user_agent=user_agent,
            ip_address=ip_address,
        )
    )
    return auth_session, raw_token


# ------------------------------------------------------------------- connexion


def login(email: str, password: str) -> LoginStep:
    """Première étape : le mot de passe. Rend un jeton intermédiaire, jamais une session."""
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

    # Le mot de passe seul n'ouvre rien : le compteur n'est remis à zéro qu'après le
    # code (ADR 0105). L'essai réservé est rendu, sans compter ni effacer d'échec.
    rate_limit.cancel_attempt(attempt)
    platform_user_id = found[0]
    with platform_transaction() as session:
        user = PlatformUserRepository(session).get(platform_user_id)
        if user is None or not user.is_active:  # désactivé entre les deux transactions
            raise AuthenticationRequiredError(_INVALID_CREDENTIALS)
        purpose = "verify" if user.mfa_enabled_at is not None else "enroll"
        raw_challenge = _open_challenge(session, user.id, purpose)
    return LoginStep(
        step=purpose,
        challenge_token=raw_challenge,
        expires_in=int(CHALLENGE_TTL.total_seconds()),
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
        elif (
            current.expires_at <= now
            or user is None
            or not user.is_active
            or user.mfa_enabled_at is None
            # 12 h depuis le mot de passe et le code, 1 h sans rafraîchissement (ADR 0105).
            or now - current.authenticated_at > SESSION_MAX_AGE
            or (successor is None and now - current.issued_at > SESSION_IDLE)
        ):
            refused = True
        else:
            rotated, new_raw_token = _issue_session(
                session,
                platform_user_id=user.id,
                family_id=current.family_id,
                user_agent=user_agent,
                ip_address=ip_address,
                authenticated_at=current.authenticated_at,
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
        mfa_enabled_at=user.mfa_enabled_at,
        recovery_codes_left=MfaRepository(session).recovery_codes_left(user.id),
    )


# ------------------------------------------------ double authentification (ADR 0105)


class MfaChallengeInvalidError(CogesError):
    """Jeton intermédiaire inconnu, échu, déjà utilisé ou d'une autre étape."""

    code = "mfa_challenge_invalid"
    status_code = 401
    default_message = "Cette étape de connexion a expiré. Reconnectez-vous."


class MfaCodeInvalidError(CogesError):
    code = "mfa_code_invalid"
    status_code = 401
    default_message = "Code incorrect. Vérifiez l'heure de votre téléphone et réessayez."


class MfaConfirmationInvalidError(MfaCodeInvalidError):
    """Code faux pour confirmer un geste dans une session ouverte : 422, pas 401 (un 401
    ferait rafraîchir la session puis renvoyer la même requête, comptée deux fois)."""

    status_code = 422


class MfaAlreadyEnabledError(BusinessRuleError):
    code = "mfa_already_enabled"
    default_message = "La double authentification de ce compte est déjà active."


class CannotResetOwnMfaError(BusinessRuleError):
    code = "cannot_reset_own_mfa"
    default_message = (
        "Vous ne pouvez pas réinitialiser votre propre double authentification : "
        "demandez-le à un autre administrateur."
    )


def _open_challenge(session: Session, platform_user_id: UUID, purpose: str) -> str:
    """Un jeton intermédiaire neuf ; ceux encore ouverts pour ce compte tombent."""
    repository = MfaRepository(session)
    now = datetime.now(UTC)
    repository.consume_open_challenges(platform_user_id, now)
    raw_token, token_hash = mfa.new_opaque_token()
    repository.add_challenge(
        PlatformMfaChallenge(
            platform_user_id=platform_user_id,
            token_hash=token_hash,
            purpose=purpose,
            created_at=now,
            expires_at=now + CHALLENGE_TTL,
        )
    )
    return raw_token


def _locked_challenge(
    session: Session, raw_token: str, purpose: str
) -> tuple[PlatformMfaChallenge, PlatformUser]:
    """Le jeton intermédiaire et son compte, verrouillés ; refus uniforme sinon."""
    repository = MfaRepository(session)
    challenge = repository.lock_challenge(mfa.opaque_token_digest(raw_token))
    now = datetime.now(UTC)
    if (
        challenge is None
        or challenge.purpose != purpose
        or challenge.consumed_at is not None
        or challenge.expires_at <= now
    ):
        raise MfaChallengeInvalidError()
    user = repository.lock_user(challenge.platform_user_id)
    if user is None or not user.is_active:
        raise MfaChallengeInvalidError()
    return challenge, user


def _challenge_owner(raw_token: str) -> tuple[UUID, str]:
    """Le compte d'un jeton intermédiaire, lu dans une courte transaction : la clé du
    freinage doit être connue **avant** de vérifier le code."""
    with platform_transaction() as session:
        repository = MfaRepository(session)
        challenge = repository.lock_challenge(mfa.opaque_token_digest(raw_token))
        if challenge is None:
            raise MfaChallengeInvalidError()
        user = PlatformUserRepository(session).get(challenge.platform_user_id)
        if user is None:
            raise MfaChallengeInvalidError()
        return user.id, user.email


def _qr_svg(uri: str) -> str:
    qr = segno.make(uri, error="m", micro=False)
    return str(qr.svg_inline(scale=5, border=2, dark="#111111", light="#ffffff"))


def start_enrollment(raw_token: str) -> MfaEnrollment:
    """Propose un secret (QR code et clé texte) ; il ne sera actif qu'après un premier
    code juste. Un nouvel appel en propose un autre."""
    with platform_transaction() as session:
        challenge, user = _locked_challenge(session, raw_token, "enroll")
        if user.mfa_enabled_at is not None:
            raise MfaAlreadyEnabledError()
        secret = totp.generate_secret()
        challenge.pending_secret = mfa.encrypt_secret(secret, user.id)
        uri = totp.provisioning_uri(secret, user.email)
        account = user.email
    return MfaEnrollment(
        secret=secret,
        otpauth_uri=uri,
        qr_svg=_qr_svg(uri),
        account=account,
        issuer=totp.ISSUER,
    )


def _record_code_failure(attempt: rate_limit.AccountAttempt, platform_user_id: UUID) -> None:
    failure = rate_limit.record_failure(attempt)
    if failure.failures == get_settings().login_throttle_alert_after:
        queue.enqueue(
            LOGIN_FAILURES_TASK,
            countdown=0,
            platform_user_id=str(platform_user_id),
            failures=failure.failures,
        )


def _new_recovery_codes(session: Session, platform_user_id: UUID, now: datetime) -> list[str]:
    repository = MfaRepository(session)
    repository.revoke_recovery_codes(platform_user_id, now)
    codes = mfa.generate_recovery_codes()
    repository.add_recovery_codes(
        platform_user_id,
        [
            mfa.recovery_code_digest(platform_user_id, cast(str, mfa.normalise_recovery_code(c)))
            for c in codes
        ],
    )
    return codes


def _recognise_device(
    session: Session,
    platform_user_id: UUID,
    device_token: str | None,
    user_agent: str | None,
    now: datetime,
) -> tuple[bool, str, str]:
    """(nouvel appareil, jeton à reposer en cookie, navigateur).

    L'appareil est un jeton aléatoire en cookie (un an) **et** son navigateur ; aucune
    adresse IP (elle change chaque jour chez la plupart des opérateurs). Un cookie qui
    change de navigateur compte comme un nouvel appareil.
    """
    repository = MfaRepository(session)
    browser = mfa.browser_label(user_agent)
    if device_token and 20 <= len(device_token) <= 200:
        known = repository.device(platform_user_id, mfa.opaque_token_digest(device_token))
        if known is not None and known.browser == browser:
            known.last_seen_at = now
            return False, device_token, browser
        if known is None:
            repository.add_device(
                PlatformKnownDevice(
                    platform_user_id=platform_user_id,
                    token_hash=mfa.opaque_token_digest(device_token),
                    browser=browser,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            return True, device_token, browser
    raw, digest = mfa.new_opaque_token()
    repository.add_device(
        PlatformKnownDevice(
            platform_user_id=platform_user_id,
            token_hash=digest,
            browser=browser,
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    return True, raw, browser


def _notify(platform_user_id: UUID, kind: str, device: str | None = None) -> None:
    """E-mail au compte (et à l'équipe), par le worker, après COMMIT."""
    queue.enqueue(
        SECURITY_NOTICE_TASK,
        countdown=0,
        platform_user_id=str(platform_user_id),
        kind=kind,
        device=device,
    )


def confirm_enrollment(
    raw_token: str,
    code: str,
    *,
    user_agent: str | None,
    ip_address: str | None,
    device_token: str | None,
) -> IssuedPlatformTokens:
    """Premier code juste : la double authentification devient active, les codes de
    secours sont tirés (montrés une fois), et la session s'ouvre."""
    platform_user_id, email = _challenge_owner(raw_token)
    attempt = rate_limit.begin_attempt(THROTTLE_SCOPE, user_id=platform_user_id, typed=email)
    accepted = False
    try:
        with platform_transaction() as session:
            challenge, user = _locked_challenge(session, raw_token, "enroll")
            if user.mfa_enabled_at is not None:
                raise MfaAlreadyEnabledError()
            if challenge.pending_secret is None:
                raise MfaChallengeInvalidError()
            secret = mfa.decrypt_secret(challenge.pending_secret, user.id)
            step = totp.matching_step(secret, code, last_step=None)
            if step is None:
                raise MfaCodeInvalidError()
            accepted = True
            now = datetime.now(UTC)
            challenge.consumed_at = now
            user.mfa_secret = challenge.pending_secret
            user.mfa_enabled_at = now
            user.mfa_last_step = step
            user.last_login_at = now
            codes = _new_recovery_codes(session, user.id, now)
            _, device, browser = _recognise_device(session, user.id, device_token, user_agent, now)
            _audit(
                session,
                actor_id=user.id,
                action="update",
                entity_table="platform_users",
                entity_id=user.id,
                diff={"mfa": "enabled", "device": browser},
                ip_address=ip_address,
            )
            _, refresh_token = _issue_session(
                session,
                platform_user_id=user.id,
                family_id=uuid4(),
                user_agent=user_agent,
                ip_address=ip_address,
                authenticated_at=now,
            )
            access_token, expires_in = create_platform_access_token(user.id, user.role)
    except MfaCodeInvalidError:
        _record_code_failure(attempt, platform_user_id)
        raise
    finally:
        if not accepted:
            rate_limit.cancel_attempt(attempt)
    rate_limit.reset_account(attempt)
    _notify(platform_user_id, "mfa_enabled", browser)
    return IssuedPlatformTokens(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=refresh_token,
        device_token=device,
        recovery_codes=tuple(codes),
    )


def verify_mfa(
    raw_token: str,
    *,
    code: str | None,
    recovery_code: str | None,
    user_agent: str | None,
    ip_address: str | None,
    device_token: str | None,
) -> IssuedPlatformTokens:
    """Seconde étape de la connexion : le code de l'application, ou un code de secours
    (usage unique, noté au journal et signalé). Même freinage que le mot de passe."""
    platform_user_id, email = _challenge_owner(raw_token)
    attempt = rate_limit.begin_attempt(THROTTLE_SCOPE, user_id=platform_user_id, typed=email)
    accepted = False
    try:
        with platform_transaction() as session:
            challenge, user = _locked_challenge(session, raw_token, "verify")
            if user.mfa_secret is None:
                raise MfaChallengeInvalidError()
            now = datetime.now(UTC)
            repository = MfaRepository(session)
            diff: dict[str, Any]
            if code is not None:
                step = totp.matching_step(
                    mfa.decrypt_secret(user.mfa_secret, user.id),
                    code,
                    last_step=user.mfa_last_step,
                )
                if step is None:
                    raise MfaCodeInvalidError()
                user.mfa_last_step = step
                diff = {"method": "totp"}
            else:
                normalised = mfa.normalise_recovery_code(recovery_code or "")
                row = (
                    repository.lock_recovery_code(
                        user.id, mfa.recovery_code_digest(user.id, normalised)
                    )
                    if normalised is not None
                    else None
                )
                if row is None:
                    raise MfaCodeInvalidError("Code de secours incorrect ou déjà utilisé.")
                row.used_at = now
                session.flush()
                diff = {
                    "method": "recovery_code",
                    "recovery_codes_left": repository.recovery_codes_left(user.id),
                }
            accepted = True
            challenge.consumed_at = now
            user.last_login_at = now
            new_device, device, browser = _recognise_device(
                session, user.id, device_token, user_agent, now
            )
            if new_device:
                diff |= {"new_device": True, "device": browser}
            _audit(
                session,
                actor_id=user.id,
                action="login",
                entity_table="platform_users",
                entity_id=user.id,
                diff=diff,
                ip_address=ip_address,
            )
            _, refresh_token = _issue_session(
                session,
                platform_user_id=user.id,
                family_id=uuid4(),
                user_agent=user_agent,
                ip_address=ip_address,
                authenticated_at=now,
            )
            access_token, expires_in = create_platform_access_token(user.id, user.role)
    except MfaCodeInvalidError:
        _record_code_failure(attempt, platform_user_id)
        raise
    finally:
        if not accepted:
            rate_limit.cancel_attempt(attempt)
    rate_limit.reset_account(attempt)
    if diff["method"] == "recovery_code":
        _notify(platform_user_id, "recovery_code_used", browser)
    if new_device:
        _notify(platform_user_id, "new_device", browser)
    return IssuedPlatformTokens(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=refresh_token,
        device_token=device,
    )


def regenerate_recovery_codes(
    admin: PlatformAdmin, code: str, *, ip_address: str | None
) -> list[str]:
    """Dix codes neufs ; les anciens ne servent plus. Exige un code de l'application."""
    with platform_transaction() as session:
        user = PlatformUserRepository(session).get(admin.platform_user_id)
        if user is None:
            raise AuthenticationRequiredError("Session invalide.")
        email = user.email
    attempt = rate_limit.begin_attempt(THROTTLE_SCOPE, user_id=admin.platform_user_id, typed=email)
    accepted = False
    try:
        with platform_transaction() as session:
            user = MfaRepository(session).lock_user(admin.platform_user_id)
            if user is None or user.mfa_secret is None:
                raise AuthenticationRequiredError("Session invalide.")
            step = totp.matching_step(
                mfa.decrypt_secret(user.mfa_secret, user.id), code, last_step=user.mfa_last_step
            )
            if step is None:
                raise MfaConfirmationInvalidError()
            accepted = True
            user.mfa_last_step = step
            codes = _new_recovery_codes(session, user.id, datetime.now(UTC))
            _audit(
                session,
                actor_id=user.id,
                action="update",
                entity_table="platform_users",
                entity_id=user.id,
                diff={"mfa": "recovery_codes_regenerated"},
                ip_address=ip_address,
            )
    except MfaCodeInvalidError:
        _record_code_failure(attempt, admin.platform_user_id)
        raise
    finally:
        if not accepted:
            rate_limit.cancel_attempt(attempt)
    rate_limit.reset_account(attempt)
    return codes


def _clear_mfa(session: Session, user: PlatformUser, now: datetime) -> int:
    """Retire secret et codes de secours ; le trigger de 0033 révoque les sessions."""
    repository = MfaRepository(session)
    user.mfa_secret = None
    user.mfa_enabled_at = None
    user.mfa_last_step = None
    repository.revoke_recovery_codes(user.id, now)
    repository.consume_open_challenges(user.id, now)
    session.flush()
    return repository.revoke_sessions(user.id, now)


def reset_member_mfa(
    session: Session,
    admin: PlatformAdmin,
    user_id: UUID,
    *,
    reason: str,
    ip_address: str | None,
) -> TeamMember:
    """Téléphone perdu : un administrateur réinitialise la double authentification d'un
    collègue (jamais la sienne). Sessions fermées, réenrôlement à la connexion suivante."""
    if user_id == admin.platform_user_id:
        raise CannotResetOwnMfaError()
    member = TeamRepository(session).lock_member(user_id)
    if member is None:
        raise NotFoundError("Compte introuvable.")
    now = datetime.now(UTC)
    revoked = _clear_mfa(session, member, now)
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="update",
        entity_table="platform_users",
        entity_id=member.id,
        diff={"mfa": "reset", "reason": reason, "revoked_sessions": revoked},
        ip_address=ip_address,
    )
    member_id = member.id
    on_commit(session, lambda: _notify(member_id, "mfa_reset"))
    return _member(member, admin)


def reset_platform_mfa(*, email: str) -> bool:
    """Dernier recours sur le serveur (CLI) : même effet, sans acteur. `False` : aucun
    compte à cette adresse."""
    with platform_transaction() as session:
        user = PlatformUserRepository(session).get_by_email(email.strip().lower())
        if user is None:
            return False
        user = MfaRepository(session).lock_user(user.id)
        assert user is not None
        revoked = _clear_mfa(session, user, datetime.now(UTC))
        _audit(
            session,
            actor_id=None,
            action="update",
            entity_table="platform_users",
            entity_id=user.id,
            diff={"mfa": "reset", "reason": "commande sur le serveur", "revoked_sessions": revoked},
        )
        user_id = user.id
    _notify(user_id, "mfa_reset")
    return True


@dataclass(frozen=True, slots=True)
class SecurityNotice:
    """Ce que le worker envoie : à qui, et quoi. Aucun secret."""

    email: str
    display_name: str


def security_notice_recipient(platform_user_id: UUID) -> SecurityNotice | None:
    with platform_transaction() as session:
        user = PlatformUserRepository(session).get(platform_user_id)
        if user is None:
            return None
        return SecurityNotice(email=user.email, display_name=user.display_name)


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
    session: Session,
    *,
    search: str | None,
    page: int,
    page_size: int,
    status: str | None = None,
) -> CompanyPage:
    rows, total = CompanyDirectory(session).search(
        search=normalise_term(search), page=page, page_size=page_size, status=status
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
    before = CompanyDirectory(session).lock_status(company_id)
    if before is None:
        raise NotFoundError("Entreprise introuvable.")
    _set_access(
        session,
        company_id,
        before=before,
        after=status,
        actor_id=admin.platform_user_id,
        reason=reason,
        ip_address=ip_address,
    )
    return get_company(session, company_id)


# -------------------------------------------------------------------------- CLI


class MfaSecretOutsideDevelopmentError(ValueError):
    """`--mfa-secret` hors `local` et `ci` : un secret connu d'avance n'est pas un facteur."""


def create_platform_user(
    *, email: str, display_name: str, role: str, password: str, mfa_secret: str | None = None
) -> UUID:
    """Crée un compte de l'équipe. Réservé à la CLI : aucune route d'inscription.

    Sans `mfa_secret`, le compte enrôle sa double authentification à sa première
    connexion. `mfa_secret` (parcours e2e) n'est accepté qu'en `local` et `ci`.
    """
    if mfa_secret is not None and get_settings().env not in DEVELOPMENT_ENVS:
        raise MfaSecretOutsideDevelopmentError(
            "--mfa-secret n'est accepté qu'en local et en CI : un compte réel enrôle sa "
            "double authentification à sa première connexion."
        )
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
        if mfa_secret is not None:
            user.mfa_secret = mfa.encrypt_secret(mfa_secret, user.id)
            user.mfa_enabled_at = datetime.now(UTC)
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


# ------------------------------------------------------------ abonnements (ADR 0091)

#: Accès (`companies.status`, lot 1) que donne chaque état d'abonnement. Changé dans la
#: même transaction que l'abonnement ; la suspension manuelle du lot 1, elle, ne touche
#: que l'accès.
ACCESS_OF: dict[str, str] = {
    "trial": "trial",
    "active": "active",
    "past_due": "active",
    "suspended": "suspended",
}

#: Les paiements montrés avec l'abonnement ; le total les compte tous.
PAYMENTS_SHOWN = 50


class PlanDowngradeTooManyUsersError(BusinessRuleError):
    """L'offre visée admet moins de comptes actifs que l'entreprise n'en a."""

    code = "plan_downgrade_too_many_users"

    def __init__(self, *, active_users: int, max_users: int) -> None:
        excess = active_users - max_users
        super().__init__(
            f"Cette offre autorise {max_users} utilisateurs ; l'entreprise en a "
            f"{active_users} actifs. Désactivez-en {excess} avant de changer d'offre.",
            details={
                "active_users": active_users,
                "max_users": max_users,
                "to_deactivate": excess,
            },
        )


def _plan_read(plan: Plan) -> PlanRead:
    return PlanRead(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        price_fcfa=plan.price_fcfa,
        semiannual_price_fcfa=plan.semiannual_price_fcfa,
        annual_price_fcfa=plan.annual_price_fcfa,
        max_users=plan.max_users,
        features=list(plan.features),
        is_orderable=plan.is_orderable,
    )


#: Offres que l'administrateur peut poser sans qu'elles soient en vente libre : Premium,
#: sur devis (ADR 0132). Le changement d'offre est réservé au profil `administrator`.
QUOTED_PLANS = frozenset({"premium"})


def _offered(plan: Plan | None) -> bool:
    return plan is not None and (plan.is_orderable or plan.code in QUOTED_PLANS)


def _cap(plan: Plan, subscription: Subscription) -> int | None:
    """Plafond effectif : le plafond acquis s'il existe, sinon celui de l'offre (comme
    `users_plan_limit()` en base)."""
    if subscription.max_users_override is not None:
        return subscription.max_users_override
    return plan.max_users


def list_plans(session: Session) -> list[PlanRead]:
    return [_plan_read(plan) for plan in SubscriptionRepository(session).plans()]


def _detail(session: Session, company_id: UUID, subscription: Subscription) -> SubscriptionDetail:
    repository = SubscriptionRepository(session)
    payments, total = repository.payments(subscription.id, limit=PAYMENTS_SHOWN)
    plan = repository.plan(subscription.plan_id)
    return SubscriptionDetail(
        company_id=company_id,
        plan=_plan_read(plan),
        status=cast(Any, subscription.status),
        trial_ends_at=subscription.trial_ends_at,
        started_at=subscription.started_at,
        current_period_end=subscription.current_period_end,
        active_users=repository.active_users(company_id),
        is_license=subscription.is_license,
        extra_features=list(subscription.extra_features),
        max_users_override=subscription.max_users_override,
        max_users=_cap(plan, subscription),
        reminder_stage=cast(Any, subscription.reminder_stage),
        reminder_for_end=subscription.reminder_for_end,
        reminder_at=subscription.reminder_at,
        payments=[
            SubscriptionPaymentRead(
                id=payment.id,
                amount_fcfa=payment.amount_fcfa,
                paid_at=payment.paid_at,
                method=cast(Any, payment.method),
                note=payment.note,
                period_months=cast(Any, payment.period_months),
                recorded_at=payment.created_at,
            )
            for payment in payments
        ],
        payments_total=total,
    )


def get_subscription(session: Session, company_id: UUID) -> SubscriptionDetail:
    if CompanyDirectory(session).get(company_id) is None:
        raise NotFoundError("Entreprise introuvable.")
    subscription = SubscriptionRepository(session).get(company_id)
    if subscription is None:
        raise NotFoundError("Abonnement introuvable.")
    return _detail(session, company_id, subscription)


def _lock(session: Session, company_id: UUID) -> tuple[str, Subscription]:
    """Verrouille l'entreprise **puis** son abonnement : l'ordre de tous les gestes."""
    access = CompanyDirectory(session).lock_status(company_id)
    subscription = SubscriptionRepository(session).lock(company_id) if access else None
    if access is None or subscription is None:
        raise NotFoundError("Entreprise introuvable.")
    return access, subscription


def _set_access(
    session: Session,
    company_id: UUID,
    *,
    before: str,
    after: str,
    actor_id: UUID | None,
    reason: str,
    ip_address: str | None = None,
    notify_manager: bool = True,
) -> None:
    """Change `companies.status`, l'audite, et prévient le gérant d'une suspension ou
    d'une réactivation (après COMMIT). Le même statut ne change rien."""
    if before == after:
        return
    CompanyDirectory(session).set_status(company_id, after)
    _audit(
        session,
        actor_id=actor_id,
        action="update",
        entity_table="companies",
        entity_id=company_id,
        target_company_id=company_id,
        diff={"before": {"status": before}, "after": {"status": after}, "reason": reason},
        ip_address=ip_address,
    )
    if notify_manager and "suspended" in (before, after) and after in ("suspended", "active"):

        def _notify_manager() -> None:
            queue.enqueue(
                STATUS_CHANGED_TASK, countdown=0, company_id=str(company_id), status=after
            )

        on_commit(session, _notify_manager)


def change_subscription(
    session: Session,
    admin: PlatformAdmin,
    company_id: UUID,
    payload: SubscriptionUpdate,
    *,
    ip_address: str | None = None,
) -> SubscriptionDetail:
    """Change d'offre ou de statut (profil `administrator`). Audit critique.

    Une offre plus petite que le nombre de comptes actifs est refusée avec le nombre à
    désactiver d'abord ; seul un changement de **statut** touche l'accès de l'entreprise.
    """
    access, subscription = _lock(session, company_id)
    repository = SubscriptionRepository(session)
    current = repository.plan(subscription.plan_id)
    before = {"plan": current.code, "status": subscription.status}

    if payload.plan_code is not None and payload.plan_code != current.code:
        plan = repository.plan_by_code(payload.plan_code)
        if plan is None or not _offered(plan):
            raise ValidationFailedError(
                "Cette offre n'est pas proposée.", details={"plan_code": payload.plan_code}
            )
        cap = _cap(plan, subscription)
        if cap is not None:
            active = repository.active_users(company_id)
            if active > cap:
                raise PlanDowngradeTooManyUsersError(active_users=active, max_users=cap)
        subscription.plan_id = plan.id
        current = plan
    if payload.status is not None:
        subscription.status = payload.status

    after = {"plan": current.code, "status": subscription.status}
    if after == before:
        return _detail(session, company_id, subscription)
    subscription.updated_at = datetime.now(UTC)
    session.flush()
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="update",
        entity_table="subscriptions",
        entity_id=subscription.id,
        target_company_id=company_id,
        diff={"before": before, "after": after, "reason": payload.reason.strip()},
        ip_address=ip_address,
    )
    if after["status"] != before["status"]:
        _set_access(
            session,
            company_id,
            before=access,
            after=ACCESS_OF[subscription.status],
            actor_id=admin.platform_user_id,
            reason=payload.reason.strip(),
            ip_address=ip_address,
        )
    return _detail(session, company_id, subscription)


def _add_months(moment: datetime, months: int) -> datetime:
    """Même jour `months` mois plus tard, ramené au dernier jour s'il n'existe pas
    (31 janvier + 1 → 28 ou 29 février ; 29 février + 12 → 28 février)."""
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    return moment.replace(year=year, month=month, day=min(moment.day, monthrange(year, month)[1]))


class PaymentAmountMismatchError(ValidationFailedError):
    """Le montant déclaré n'est pas le prix de l'offre pour la durée choisie (ADR 0132)."""

    code = "payment_amount_mismatch"


class AnnualPaymentUnavailableError(ValidationFailedError):
    code = "annual_payment_unavailable"
    default_message = "Cette offre ne se paie pas à l'année."


class SemiannualPaymentUnavailableError(ValidationFailedError):
    code = "semiannual_payment_unavailable"
    default_message = "Cette offre ne se paie pas par 6 mois."


def _expected_amount(plan: Plan, period_months: int) -> Decimal | None:
    """Le montant exigé, ou `None` pour une offre sur devis (tout montant positif)."""
    if plan.price_fcfa is None:
        return None
    if period_months == 6:
        if plan.semiannual_price_fcfa is None:
            raise SemiannualPaymentUnavailableError(details={"plan_code": plan.code})
        return plan.semiannual_price_fcfa
    if period_months == 12:
        if plan.annual_price_fcfa is None:
            raise AnnualPaymentUnavailableError(details={"plan_code": plan.code})
        return plan.annual_price_fcfa
    return plan.price_fcfa


def record_payment(
    session: Session,
    admin: PlatformAdmin,
    company_id: UUID,
    payload: SubscriptionPaymentCreate,
    *,
    idempotency_key: str,
    ip_address: str | None = None,
) -> tuple[SubscriptionDetail, bool]:
    """Enregistre un paiement déclaré : l'abonnement devient actif, sa période avance
    (depuis l'ancienne échéance pour un renouvellement, sinon depuis aujourd'hui :
    `_period_start`, ADR 0133), et une entreprise suspendue retrouve l'accès. Même clé,
    même paiement : rien n'est refait (le second élément dit si c'est un rejeu).
    """
    access, subscription = _lock(session, company_id)
    repository = SubscriptionRepository(session)
    replayed = repository.payment_by_key(idempotency_key)
    if replayed is not None:
        if replayed.subscription_id != subscription.id:
            raise IdempotencyKeyReusedError()
        return _detail(session, company_id, subscription), True

    expected = _expected_amount(repository.plan(subscription.plan_id), payload.period_months)
    if expected is not None and payload.amount_fcfa != expected:
        raise PaymentAmountMismatchError(
            f"Le montant attendu est de {expected:,.0f} FCFA.".replace(",", "\u202f"),
            details={"expected_amount_fcfa": str(expected), "period_months": payload.period_months},
        )

    now = datetime.now(UTC)
    payment = repository.add_payment(
        SubscriptionPayment(
            subscription_id=subscription.id,
            amount_fcfa=payload.amount_fcfa,
            paid_at=payload.paid_at,
            method=payload.method,
            note=payload.note.strip() if payload.note and payload.note.strip() else None,
            period_months=payload.period_months,
            recorded_by=admin.platform_user_id,
            idempotency_key=idempotency_key,
        )
    )
    before = {
        "status": subscription.status,
        "current_period_end": _iso(subscription.current_period_end),
    }
    period_start = _period_start(subscription, now)
    subscription.status = "active"
    subscription.current_period_end = _add_months(period_start, payload.period_months)
    subscription.updated_at = now
    session.flush()
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="insert",
        entity_table="subscription_payments",
        entity_id=payment.id,
        target_company_id=company_id,
        diff={
            "after": {
                "amount_fcfa": str(payment.amount_fcfa),
                "method": payment.method,
                "paid_at": payment.paid_at.isoformat(),
                "period_months": payment.period_months,
            },
            "subscription": {
                "before": before,
                "after": {
                    "status": subscription.status,
                    "current_period_end": _iso(subscription.current_period_end),
                },
            },
        },
        ip_address=ip_address,
    )
    _set_access(
        session,
        company_id,
        before=access,
        after=ACCESS_OF[subscription.status],
        actor_id=admin.platform_user_id,
        reason="paiement enregistré",
        ip_address=ip_address,
    )
    return _detail(session, company_id, subscription), False


def _period_start(subscription: Subscription, now: datetime) -> datetime:
    """D'où part la période payée (ADR 0133, choix du propriétaire).

    Renouvellement (une période payée en cours ou dans sa grâce) : depuis l'ancienne
    échéance, les jours de grâce ne sont pas offerts. Fin d'essai, boutique mise en
    pause, échéance oubliée depuis longtemps : depuis le jour du paiement.
    """
    ends = subscription.current_period_end
    if ends is None or subscription.status == "suspended":
        return now
    if ends >= now - timedelta(days=renewal.GRACE_DAYS):
        return ends
    return now


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


class UnknownFeatureError(ValidationFailedError):
    code = "unknown_feature"
    default_message = "Ce droit n'existe pas ou ne s'accorde pas."


def set_acquired_rights(
    session: Session,
    admin: PlatformAdmin,
    company_id: UUID,
    payload: AcquiredRightsUpdate,
    *,
    ip_address: str | None = None,
) -> SubscriptionDetail:
    """Accorde ou retire des droits acquis (profil `administrator`, ADR 0132).

    Seuls les droits qu'une offre réserve s'accordent (`plan_features.GRANTABLE`). Un
    plafond acquis plus bas que les comptes actifs est refusé comme une descente d'offre ;
    le retirer aussi, si l'offre seule n'y suffit pas. Audit critique, avec la raison.
    """
    unknown = sorted(set(payload.extra_features) - plan_features.GRANTABLE)
    if unknown:
        raise UnknownFeatureError(details={"features": unknown})
    _access, subscription = _lock(session, company_id)
    repository = SubscriptionRepository(session)
    plan = repository.plan(subscription.plan_id)
    before = {
        "extra_features": list(subscription.extra_features),
        "max_users_override": subscription.max_users_override,
    }
    after = {
        "extra_features": sorted(set(payload.extra_features)),
        "max_users_override": payload.max_users_override,
    }
    unchanged = (
        sorted(subscription.extra_features) == after["extra_features"]
        and subscription.max_users_override == payload.max_users_override
    )
    if unchanged:
        return _detail(session, company_id, subscription)
    cap = payload.max_users_override if payload.max_users_override is not None else plan.max_users
    if cap is not None:
        active = repository.active_users(company_id)
        if active > cap:
            raise PlanDowngradeTooManyUsersError(active_users=active, max_users=cap)
    subscription.extra_features = after["extra_features"]  # type: ignore[assignment]
    subscription.max_users_override = payload.max_users_override
    subscription.updated_at = datetime.now(UTC)
    session.flush()
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="update",
        entity_table="subscriptions",
        entity_id=subscription.id,
        target_company_id=company_id,
        diff={"before": before, "after": after, "reason": payload.reason.strip()},
        ip_address=ip_address,
    )
    return _detail(session, company_id, subscription)


# ------------------------------------------------- licence sur site (ADR 0125)
#
# Sur le PC d'un client, l'administration de la plateforme n'existe pas. La licence est
# un abonnement `active` **sans fin de période** : la tâche de nuit ne suit que les
# essais, elle ne le suspendra jamais. Ces deux fonctions ne sont appelées que par la
# commande `python -m app.cli activate-license` / `license-status` (test d'architecture) :
# sans elle, rien ne change. Aucun compte de l'équipe n'agit : `actor_id=None`, comme la
# tâche de nuit.

#: Raison écrite au journal de la plateforme ; elle désigne aussi les lignes de licence.
LICENSE_REASON = "licence sur site"

#: Longueur maximale de la note libre (date du contrat, fin de maintenance…).
LICENSE_NOTE_MAX = 500

#: Taille de page de la recherche par identifiant de connexion.
_SLUG_PAGE = 100


@dataclass(frozen=True, slots=True)
class LicenseResult:
    """Ce que la commande a fait, pour l'afficher en mots."""

    company_id: UUID
    company_name: str
    slug: str
    plan_code: str
    plan_name: str
    #: `None` : sans plafond.
    max_users: int | None
    active_users: int
    status_before: str
    status_after: str
    access_before: str
    access_after: str
    #: Faux : licence déjà active sur cette offre, rien écrit.
    changed: bool


@dataclass(frozen=True, slots=True)
class LicenseStatus:
    company_name: str
    slug: str
    access: str
    subscription_status: str
    plan_code: str
    plan_name: str
    max_users: int | None
    active_users: int
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    last_license_at: datetime | None
    last_license_note: str | None


def _company_by_slug(session: Session, slug: str) -> CompanyRow:
    """L'entreprise vivante dont l'identifiant de connexion est exactement `slug`.

    Passe par la recherche de l'administration (colonnes déjà accordées au rôle) puis
    garde l'égalité stricte : un identifiant qui en contient un autre ne le désigne pas.
    """
    wanted = slug.strip().lower()
    if not wanted:
        raise NotFoundError("Entreprise introuvable.", details={"slug": slug})
    directory = CompanyDirectory(session)
    page = 1
    while True:
        rows, total = directory.search(search=wanted, page=page, page_size=_SLUG_PAGE)
        for row in rows:
            if row.slug.lower() == wanted:
                return row
        if page * _SLUG_PAGE >= total:
            raise NotFoundError("Entreprise introuvable.", details={"slug": slug})
        page += 1


def _license_note(note: str | None) -> str | None:
    cleaned = note.strip() if note else ""
    if len(cleaned) > LICENSE_NOTE_MAX:
        raise ValidationFailedError(
            f"La note fait au plus {LICENSE_NOTE_MAX} caractères.",
            details={"length": len(cleaned)},
        )
    return cleaned or None


def activate_license(*, slug: str, plan_code: str, note: str | None = None) -> LicenseResult:
    """Pose la licence sur site : abonnement `active` sans fin, offre `plan_code`, accès
    rendu. Une transaction, sous `coges_app_platform`, verrous dans l'ordre de `_lock`.

    Même offre sur une licence déjà active : rien n'est écrit (`changed` faux). Une offre
    plus petite que le nombre de comptes actifs est refusée comme dans l'administration.
    Aucun message au gérant (pas de SMTP sur site) ; audit critique sans secret.
    """
    cleaned_note = _license_note(note)
    with platform_transaction() as session:
        company = _company_by_slug(session, slug)
        access, subscription = _lock(session, company.id)
        repository = SubscriptionRepository(session)
        plan = repository.plan_by_code(plan_code.strip().lower())
        if plan is None or not _offered(plan):
            raise ValidationFailedError(
                "Cette offre n'est pas proposée.", details={"plan_code": plan_code}
            )
        current = repository.plan(subscription.plan_id)
        active = repository.active_users(company.id)
        before = {
            "plan": current.code,
            "status": subscription.status,
            "current_period_end": _iso(subscription.current_period_end),
            "license": subscription.is_license,
        }
        after = {
            "plan": plan.code,
            "status": "active",
            "current_period_end": None,
            "license": True,
        }
        cap = _cap(plan, subscription)
        access_after = ACCESS_OF["active"]

        def result(changed: bool) -> LicenseResult:
            return LicenseResult(
                company_id=company.id,
                company_name=company.name,
                slug=company.slug,
                plan_code=plan.code,
                plan_name=plan.name,
                max_users=cap,
                active_users=active,
                status_before=str(before["status"]),
                status_after="active",
                access_before=access,
                access_after=access_after,
                changed=changed,
            )

        if before == after and access == access_after:
            return result(False)
        if plan.id != current.id and cap is not None and active > cap:
            raise PlanDowngradeTooManyUsersError(active_users=active, max_users=cap)

        if before != after:
            # `trial_ends_at` reste tel quel : la contrainte ne l'exige que pour un essai,
            # et la date garde la trace de l'essai d'origine.
            subscription.plan_id = plan.id
            subscription.status = "active"
            subscription.current_period_end = None
            subscription.is_license = True
            subscription.updated_at = datetime.now(UTC)
            session.flush()
            _audit(
                session,
                actor_id=None,
                action="update",
                entity_table="subscriptions",
                entity_id=subscription.id,
                target_company_id=company.id,
                diff={
                    "before": before,
                    "after": after,
                    "reason": LICENSE_REASON,
                    "note": cleaned_note,
                },
            )
        _set_access(
            session,
            company.id,
            before=access,
            after=access_after,
            actor_id=None,
            reason=LICENSE_REASON,
            notify_manager=False,
        )
        return result(True)


def license_status(*, slug: str) -> LicenseStatus:
    """État de la licence d'une entreprise, en lecture seule (support, CI)."""
    with platform_transaction() as session:
        company = _company_by_slug(session, slug)
        repository = SubscriptionRepository(session)
        subscription = repository.get(company.id)
        if subscription is None:
            raise NotFoundError("Abonnement introuvable.", details={"slug": slug})
        plan = repository.plan(subscription.plan_id)
        last_at: datetime | None = None
        last_note: str | None = None
        reader = AuditReader(session)
        page = 1
        while last_at is None:
            rows, total = reader.search(
                actor_id=None,
                action="update",
                company_id=company.id,
                entity_id=subscription.id,
                start=None,
                stop=None,
                page=page,
                page_size=_SLUG_PAGE,
            )
            for row in rows:
                diff = row.diff if isinstance(row.diff, dict) else {}
                if row.entity_table == "subscriptions" and diff.get("reason") == LICENSE_REASON:
                    last_at, last_note = row.occurred_at, diff.get("note")
                    break
            if page * _SLUG_PAGE >= total:
                break
            page += 1
        return LicenseStatus(
            company_name=company.name,
            slug=company.slug,
            access=company.status,
            subscription_status=subscription.status,
            plan_code=plan.code,
            plan_name=plan.name,
            max_users=plan.max_users,
            active_users=repository.active_users(company.id),
            trial_ends_at=subscription.trial_ends_at,
            current_period_end=subscription.current_period_end,
            last_license_at=last_at,
            last_license_note=last_note,
        )


# ------------------------------------------------------------- la tâche de nuit

#: Raisons écrites au journal par la tâche de nuit (audit sans acteur).
TRIAL_PAUSE_REASON = "fin de l'essai sans paiement"
PAID_PAUSE_REASON = "échéance dépassée sans paiement"
#: Une échéance qui tombe d'ici là peut être « demain » dans un fuseau en avance.
_LOOKAHEAD = timedelta(days=2)


@dataclass(frozen=True, slots=True)
class RenewalNotice:
    """Ce que la tâche de nuit doit dire à une entreprise, après COMMIT (ADR 0133)."""

    company_id: UUID
    company_name: str
    stage: renewal.Stage
    kind: renewal.Kind
    ends_at: datetime
    plan_name: str
    #: Jour de la pause au plus tôt, et jour de la tâche, dans le fuseau de l'entreprise.
    pause_on: date
    today: date


def run_subscription_day(now: datetime | None = None) -> list[RenewalNotice]:
    """Relances et suspension (ADR 0133) : veille, jour J (`past_due`, accès gardé),
    dernier rappel à J+2, pause à J+3, pour un essai comme pour une période payée.

    Une seule transaction, sous `coges_app_platform`. L'étape franchie est gardée avec
    son échéance (`reminder_stage`, `reminder_for_end`, `reminder_at`) : relancer la
    tâche ne refait rien, une nuit manquée ne donne que l'étape du jour, et la pause
    n'arrive qu'après un dernier rappel donné un jour précédent. Les messages partent
    **après** le COMMIT, par l'appelant.
    """
    moment = now or datetime.now(UTC)
    notices: list[RenewalNotice] = []
    with platform_transaction() as session:
        directory = CompanyDirectory(session)
        repository = SubscriptionRepository(session)
        for company_id in repository.deadlines_before(moment + _LOOKAHEAD):
            access = directory.lock_status(company_id)
            subscription = repository.lock(company_id) if access else None
            if access is None or subscription is None:
                continue
            found = renewal.deadline(
                status=subscription.status,
                trial_ends_at=subscription.trial_ends_at,
                current_period_end=subscription.current_period_end,
                is_license=subscription.is_license,
            )
            if found is None:
                continue
            tz = renewal.zone(repository.timezone(company_id))
            today = renewal.local_day(moment, tz)
            same_end = subscription.reminder_for_end == found.ends_at
            done = subscription.reminder_stage if same_end else None
            done_on = (
                renewal.local_day(subscription.reminder_at, tz)
                if same_end and subscription.reminder_at is not None
                else None
            )
            stage = renewal.next_stage(
                offset=renewal.offset_days(found.ends_at, moment, tz),
                done=done,
                done_on=done_on,
                today=today,
            )
            if stage is None:
                continue
            before = {"status": subscription.status, "reminder_stage": done}
            subscription.reminder_stage = stage
            subscription.reminder_for_end = found.ends_at
            subscription.reminder_at = moment
            subscription.updated_at = moment
            if stage == "suspended":
                reason = TRIAL_PAUSE_REASON if found.kind == "trial" else PAID_PAUSE_REASON
                subscription.status = "suspended"
                session.flush()
                _audit(
                    session,
                    actor_id=None,
                    action="update",
                    entity_table="subscriptions",
                    entity_id=subscription.id,
                    target_company_id=company_id,
                    diff={
                        "before": before,
                        "after": {"status": "suspended", "reminder_stage": stage},
                        "ends_at": found.ends_at.isoformat(),
                        "reason": reason,
                    },
                )
                # Le gérant reçoit le message chaleureux « en pause », pas celui d'une
                # suspension décidée par l'équipe.
                _set_access(
                    session,
                    company_id,
                    before=access,
                    after="suspended",
                    actor_id=None,
                    reason=reason,
                    notify_manager=False,
                )
            elif stage in ("due", "last") and subscription.status != "past_due":
                # Délai de grâce : l'abonnement est en retard, l'accès ne change pas.
                subscription.status = "past_due"
            session.flush()
            company = directory.get(company_id)
            notices.append(
                RenewalNotice(
                    company_id=company_id,
                    company_name=company.name if company else "",
                    stage=stage,
                    kind=found.kind,
                    ends_at=found.ends_at,
                    plan_name=repository.plan(subscription.plan_id).name,
                    pause_on=renewal.pause_day(found.ends_at, tz),
                    today=today,
                )
            )
    return notices


# ------------------------------------------------- prolonger, à relancer (ADR 0133)

EXTEND_DAYS_MAX = 90


def extend_subscription(
    session: Session,
    admin: PlatformAdmin,
    company_id: UUID,
    payload: SubscriptionExtend,
    *,
    ip_address: str | None = None,
) -> SubscriptionDetail:
    """« Prolonger » : N jours ajoutés à l'échéance (ou à aujourd'hui si elle est passée),
    calendrier des relances remis à zéro, accès rendu à une boutique mise en pause.

    Un essai reste un essai (`trial_ends_at`), une période payée reste payée
    (`current_period_end`). Audit critique avec la raison.
    """
    access, subscription = _lock(session, company_id)
    if subscription.is_license:
        raise ValidationFailedError("Une licence sur site n'a pas d'échéance à prolonger.")
    now = datetime.now(UTC)
    paid = subscription.current_period_end is not None
    ends = subscription.current_period_end if paid else subscription.trial_ends_at
    if ends is None:
        raise ValidationFailedError("Cet abonnement n'a pas d'échéance à prolonger.")
    new_end = max(ends, now) + timedelta(days=payload.days)
    before = {
        "status": subscription.status,
        "trial_ends_at": _iso(subscription.trial_ends_at),
        "current_period_end": _iso(subscription.current_period_end),
        "reminder_stage": subscription.reminder_stage,
    }
    if paid:
        subscription.current_period_end = new_end
        subscription.status = "active"
    else:
        subscription.trial_ends_at = new_end
        subscription.status = "trial"
    subscription.reminder_stage = None
    subscription.reminder_for_end = None
    subscription.reminder_at = None
    subscription.updated_at = now
    session.flush()
    reason = payload.reason.strip()
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="update",
        entity_table="subscriptions",
        entity_id=subscription.id,
        target_company_id=company_id,
        diff={
            "before": before,
            "after": {
                "status": subscription.status,
                "trial_ends_at": _iso(subscription.trial_ends_at),
                "current_period_end": _iso(subscription.current_period_end),
                "reminder_stage": None,
            },
            "days": payload.days,
            "reason": reason,
        },
        ip_address=ip_address,
    )
    if access == "suspended" and before["status"] == "suspended":
        _set_access(
            session,
            company_id,
            before=access,
            after=ACCESS_OF[subscription.status],
            actor_id=admin.platform_user_id,
            reason=reason,
            ip_address=ip_address,
        )
    return _detail(session, company_id, subscription)


#: « À relancer » : de J-1 à J+3, et les boutiques mises en pause depuis moins de 7 jours.
REMINDERS_PAUSED_WINDOW = timedelta(days=7)


def _reminder_item(row: Any, now: datetime, contacts: list[Any]) -> ReminderItem | None:
    tz = renewal.zone(row.timezone)
    today = renewal.local_day(now, tz)
    if row.status == "suspended":
        if row.reminder_for_end is None:
            return None
        kind: renewal.Kind = "paid" if row.current_period_end == row.reminder_for_end else "trial"
        ends = row.reminder_for_end
        stage: renewal.Stage = "suspended"
    else:
        found = renewal.deadline(
            status=row.status,
            trial_ends_at=row.trial_ends_at,
            current_period_end=row.current_period_end,
            is_license=row.is_license,
        )
        if found is None:
            return None
        offset = renewal.offset_days(found.ends_at, now, tz)
        if not -1 <= offset <= renewal.GRACE_DAYS:
            return None
        calendar = renewal.calendar_stage(offset)
        if calendar is None:
            return None
        stage = "last" if calendar == "suspended" else calendar
        kind, ends = found.kind, found.ends_at
    pause_on = renewal.pause_day(ends, tz)
    days_left = max(1, (pause_on - today).days)
    sent = row.reminder_stage if row.reminder_for_end == ends else None
    text_ = renewal.message(stage, kind, row.plan_name, days_left)
    return ReminderItem(
        company_id=row.company_id,
        name=row.name,
        slug=row.slug,
        status=row.status,
        kind=kind,
        stage=stage,
        sent_stage=cast(Any, sent),
        ends_at=ends,
        pause_on=pause_on,
        plan_name=row.plan_name,
        message=f"Bonjour, c'est l'équipe CoGes pour {row.name}. {text_}",
        contacts=[
            ReminderContact(full_name=contact.full_name, phone=contact.phone)
            for contact in contacts
        ],
    )


def reminders(session: Session) -> ReminderList:
    now = clock.now()
    repository = SubscriptionRepository(session)
    rows = repository.reminder_candidates(
        since=now - timedelta(days=renewal.GRACE_DAYS + 2),
        until=now + _LOOKAHEAD,
        paused_since=now - REMINDERS_PAUSED_WINDOW,
    )
    by_company: dict[UUID, list[Any]] = {}
    for contact in repository.manager_contacts([row.company_id for row in rows]):
        by_company.setdefault(contact.company_id, []).append(contact)
    items = [
        item
        for row in rows
        if (item := _reminder_item(row, now, by_company.get(row.company_id, []))) is not None
    ]
    return ReminderList(computed_at=now, items=items)


# ------------------------------------------------- accès support encadré (ADR 0092)

SUPPORT_NOTICE_TASK = "platform.support_notice"
#: Les sessions montrées sur la fiche entreprise.
SUPPORT_SESSIONS_SHOWN = 20


class SupportSessionAlreadyOpenError(BusinessRuleError):
    code = "support_session_already_open"

    def __init__(self) -> None:
        super().__init__(
            "Un accès support est déjà ouvert pour cette entreprise. "
            "Reprenez-le, ou fermez-le avant d'en ouvrir un autre."
        )


class SupportSessionClosedError(BusinessRuleError):
    code = "support_session_closed"

    def __init__(self) -> None:
        super().__init__("Cet accès support est déjà terminé.")


class SupportSessionNotYoursError(BusinessRuleError):
    code = "support_session_not_yours"

    def __init__(self) -> None:
        super().__init__(
            "Seule la personne qui a ouvert cet accès peut s'en servir. "
            "Fermez-le, puis ouvrez le vôtre avec votre justification."
        )


class SupportCompanySuspendedError(BusinessRuleError):
    code = "support_company_suspended"

    def __init__(self) -> None:
        super().__init__(
            "Cette entreprise est suspendue : un accès support serait refusé comme les "
            "autres. Réactivez-la d'abord si c'est nécessaire."
        )


def _support_read(
    row: SupportSession, opened_by: str, me: UUID, now: datetime
) -> SupportSessionRead:
    return SupportSessionRead(
        id=row.id,
        company_id=row.company_id,
        opened_by=opened_by,
        opened_by_me=row.platform_user_id == me,
        justification=row.justification,
        started_at=row.started_at,
        expires_at=row.expires_at,
        ended_at=row.ended_at,
        is_open=row.ended_at is None and row.expires_at > now,
    )


def _company_journal(
    company_id: UUID,
    *,
    action: AuditAction,
    session_id: UUID,
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> None:
    """Écrit le geste dans le journal d'activité **de l'entreprise** (ADR 0092).

    Par le chemin de tout utilisateur : `coges_app`, `SET LOCAL app.company_id` sur
    l'entreprise visée, la RLS normale. Seule exception assumée à « Platform ne parle
    qu'à `coges_app_platform` » : l'entreprise doit lire dans son propre journal qu'un
    accès a eu lieu. Auteur nul : « l'équipe CoGes », jamais le nom d'une personne.

    Validé **avant** la transaction de l'administration : un jeton n'est rendu qu'une
    fois les deux validées, donc aucun accès utilisable sans trace chez l'entreprise.
    """
    with tenant_transaction(TenantContext.bootstrap(company_id)) as tenant_session:
        audit_critical(
            tenant_session,
            TenantContext.bootstrap(company_id),
            action=action,
            entity_table="support_sessions",
            entity_id=session_id,
            before=before,
            after=after,
        )


def list_support_sessions(
    session: Session, admin: PlatformAdmin, company_id: UUID
) -> SupportSessionList:
    if CompanyDirectory(session).get(company_id) is None:
        raise NotFoundError("Entreprise introuvable.")
    now = datetime.now(UTC)
    recent = [
        _support_read(row, name, admin.platform_user_id, now)
        for row, name in SupportSessionRepository(session).recent(
            company_id, limit=SUPPORT_SESSIONS_SHOWN
        )
    ]
    active = next((item for item in recent if item.is_open), None)
    return SupportSessionList(active=active, recent=recent)


def open_support_session(
    session: Session,
    admin: PlatformAdmin,
    company_id: UUID,
    payload: SupportSessionCreate,
    *,
    ip_address: str | None = None,
) -> SupportAccessToken:
    """Bris de glace : ouvre l'accès, l'écrit dans les deux journaux, rend le jeton."""
    company = CompanyDirectory(session).get(company_id)
    if company is None:
        raise NotFoundError("Entreprise introuvable.")
    if company.status == "suspended":
        raise SupportCompanySuspendedError()
    repository = SupportSessionRepository(session)
    now = datetime.now(UTC)
    repository.close_expired(now, company_id=company_id)
    if repository.open_for(company_id) is not None:
        raise SupportSessionAlreadyOpenError()
    try:
        row = repository.add(
            SupportSession(
                company_id=company_id,
                platform_user_id=admin.platform_user_id,
                justification=payload.justification,
                started_at=now,
                expires_at=now + timedelta(minutes=payload.duration_minutes),
            )
        )
    except IntegrityError as exc:  # une ouverture simultanée a gagné l'index unique
        raise SupportSessionAlreadyOpenError() from exc

    trace = {
        "justification": row.justification,
        "started_at": row.started_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
    }
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="insert",
        entity_table="support_sessions",
        entity_id=row.id,
        target_company_id=company_id,
        diff={"after": {**trace, "duration_minutes": payload.duration_minutes}},
        ip_address=ip_address,
    )
    _company_journal(
        company_id, action=AuditAction.INSERT, session_id=row.id, before=None, after=trace
    )

    def _notify() -> None:
        queue.enqueue(
            SUPPORT_NOTICE_TASK,
            countdown=0,
            company_id=str(company_id),
            session_id=str(row.id),
            expires_at=row.expires_at.isoformat(),
        )

    on_commit(session, _notify)
    token, expires_in = create_support_access_token(row.id, company_id, row.expires_at)
    return SupportAccessToken(
        session=_support_read(row, admin_name(session, admin), admin.platform_user_id, now),
        access_token=token,
        expires_in=expires_in,
    )


def admin_name(session: Session, admin: PlatformAdmin) -> str:
    user = PlatformUserRepository(session).get(admin.platform_user_id)
    return user.display_name if user else ""


def issue_support_token(
    session: Session,
    admin: PlatformAdmin,
    session_id: UUID,
    *,
    ip_address: str | None = None,
) -> SupportAccessToken:
    """Redonne le jeton d'une session ouverte (l'administration l'a perdu en rechargeant).

    À qui l'a ouverte seulement : la justification et le journal portent son nom."""
    row = SupportSessionRepository(session).lock(session_id)
    now = datetime.now(UTC)
    if row is None:
        raise NotFoundError("Accès support introuvable.")
    if row.ended_at is not None or row.expires_at <= now:
        raise SupportSessionClosedError()
    if row.platform_user_id != admin.platform_user_id:
        raise SupportSessionNotYoursError()
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="login",
        entity_table="support_sessions",
        entity_id=row.id,
        target_company_id=row.company_id,
        diff={"after": {"token_issued_at": now.isoformat()}},
        ip_address=ip_address,
    )
    token, expires_in = create_support_access_token(row.id, row.company_id, row.expires_at)
    return SupportAccessToken(
        session=_support_read(row, admin_name(session, admin), admin.platform_user_id, now),
        access_token=token,
        expires_in=expires_in,
    )


def close_support_session(
    session: Session,
    admin: PlatformAdmin,
    session_id: UUID,
    *,
    ip_address: str | None = None,
) -> None:
    """Ferme l'accès avant l'heure : le jeton cesse de servir à la requête suivante."""
    row = SupportSessionRepository(session).lock(session_id)
    now = datetime.now(UTC)
    if row is None:
        raise NotFoundError("Accès support introuvable.")
    if row.ended_at is not None or row.expires_at <= now:
        raise SupportSessionClosedError()
    row.ended_at = now
    row.ended_by = admin.platform_user_id
    session.flush()
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="update",
        entity_table="support_sessions",
        entity_id=row.id,
        target_company_id=row.company_id,
        diff={"before": {"ended_at": None}, "after": {"ended_at": now.isoformat()}},
        ip_address=ip_address,
    )
    _company_journal(
        row.company_id,
        action=AuditAction.UPDATE,
        session_id=row.id,
        before={"ended_at": None},
        after={"ended_at": now.isoformat(), "expires_at": row.expires_at.isoformat()},
    )


def close_expired_support_sessions(now: datetime | None = None) -> int:
    """Tâche de nuit : `ended_at = expires_at` pour les sessions échues restées ouvertes.

    Le jeton ne servait déjà plus (relu à chaque requête) : la liste des sessions
    ouvertes redevient exacte, rien de plus."""
    with platform_transaction() as session:
        return len(SupportSessionRepository(session).close_expired(now or datetime.now(UTC)))


def support_justification(session_id: UUID) -> str | None:
    """Le « pourquoi » d'une session, pour l'e-mail au gérant (worker)."""
    with platform_transaction() as session:
        row = session.get(SupportSession, session_id)
        return None if row is None else row.justification


# ---------------------------------------------------------- statistiques (ADR 0093)

#: L'horloge des statistiques : Dakar, à l'heure de Greenwich toute l'année.
STATS_TIMEZONE = "Africa/Dakar"
#: Plus longue période personnalisée du revenu, bornes comprises.
STATS_MAX_DAYS = 366
SIGNUP_MONTHS = 12
SIGNUP_WEEKS = 52


class PeriodDatesRequiredError(ValidationFailedError):
    code = "period_dates_required"
    default_message = "Une période personnalisée demande une date de début et une date de fin."


class PeriodInvertedError(ValidationFailedError):
    code = "period_inverted"
    default_message = "La date de début doit précéder la date de fin."


class PeriodTooLongError(ValidationFailedError):
    code = "period_too_long"
    default_message = f"La période ne peut pas dépasser {STATS_MAX_DAYS} jours."


class PeriodInFutureError(ValidationFailedError):
    code = "period_in_future"
    default_message = "La période ne peut pas finir après aujourd'hui."


def stats_overview(session: Session) -> StatsOverview:
    row = StatsRepository(session).overview()
    return StatsOverview(
        computed_at=clock.now(),
        companies=CompanyStatusCounts(
            trial=row.trial, active=row.active, suspended=row.suspended, total=row.total
        ),
        active_users=row.active_users,
        plans=[
            PlanBreakdown(
                code=plan["code"],
                name=plan["name"],
                trial=plan["trial"],
                paying=plan["paying"],
                suspended=plan["suspended"],
                total=plan["total"],
            )
            for plan in row.plans
        ],
        without_subscription=row.without_subscription,
    )


def _shift_month(day: date, months: int) -> date:
    """Le premier du mois, `months` mois plus tôt (négatif) ou plus tard."""
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _period_days(
    period: StatsPeriod, start: date | None, end: date | None, today: date
) -> tuple[date, date]:
    if period == "current_month":
        return today.replace(day=1), today
    if period == "previous_month":
        first = _shift_month(today, -1)
        return first, today.replace(day=1) - timedelta(days=1)
    if start is None or end is None:
        raise PeriodDatesRequiredError()
    if start > end:
        raise PeriodInvertedError(details={"start": start.isoformat(), "end": end.isoformat()})
    if end > today:
        raise PeriodInFutureError(details={"end": end.isoformat(), "today": today.isoformat()})
    if (end - start).days + 1 > STATS_MAX_DAYS:
        raise PeriodTooLongError(details={"max_days": STATS_MAX_DAYS})
    return start, end


def stats_revenue(
    session: Session, period: StatsPeriod, start: date | None, end: date | None
) -> RevenueRead:
    """L'argent déclaré reçu, pas ce que les offres en cours « devraient » rapporter."""
    now = clock.now()
    zone = ZoneInfo(STATS_TIMEZONE)
    first, last = _period_days(period, start, end, now.astimezone(zone).date())
    total, count = StatsRepository(session).revenue(
        datetime.combine(first, time.min, tzinfo=zone),
        datetime.combine(last + timedelta(days=1), time.min, tzinfo=zone),
    )
    return RevenueRead(
        period=period,
        start=first,
        end=last,
        timezone=STATS_TIMEZONE,
        total_fcfa=total,
        payment_count=count,
        computed_at=now,
    )


def stats_signups(session: Session, granularity: StatsGranularity) -> SignupsRead:
    now = clock.now()
    zone = ZoneInfo(STATS_TIMEZONE)
    today = now.astimezone(zone).date()
    if granularity == "month":
        starts = [_shift_month(today, back) for back in range(1 - SIGNUP_MONTHS, 1)]
        ends = [_shift_month(day, 1) - timedelta(days=1) for day in starts]
    else:
        monday = today - timedelta(days=today.weekday())
        starts = [monday - timedelta(weeks=back) for back in range(SIGNUP_WEEKS - 1, -1, -1)]
        ends = [day + timedelta(days=6) for day in starts]
    counts = StatsRepository(session).signups(
        unit=granularity,
        zone=STATS_TIMEZONE,
        since=datetime.combine(starts[0], time.min, tzinfo=zone),
    )
    buckets = [
        SignupBucket(start=first, end=last, count=counts.get(first, 0))
        for first, last in zip(starts, ends, strict=True)
    ]
    return SignupsRead(
        granularity=granularity,
        timezone=STATS_TIMEZONE,
        computed_at=now,
        buckets=buckets,
        total=sum(bucket.count for bucket in buckets),
    )


# ------------------------------------------------------- équipe et accès (ADR 0094)

#: Envoi d'une invitation par le worker (`app/workers/tasks/platform.py`).
SEND_INVITATION_TASK = "platform.send_invitation"
INVITATION_TTL = timedelta(hours=72)
#: « Qui expire bientôt » : le tableau de bord et le bilan de l'équipe.
INVITATION_SOON = timedelta(hours=24)
TRIAL_SOON = timedelta(days=7)
#: Clés du `diff` qu'on montre dans le journal ; tout le reste est retiré, jamais un secret.
AUDIT_FIELDS = frozenset(
    {
        "after",
        "amount_fcfa",
        "before",
        "current_period_end",
        "device",
        "display_name",
        "duration_minutes",
        "email",
        "ended_at",
        "expires_at",
        "is_active",
        "issue",
        "justification",
        "method",
        "mfa",
        "new_device",
        "paid_at",
        "plan",
        "reason",
        "recovery_codes_left",
        "revoked_sessions",
        "role",
        "started_at",
        "status",
        "subscription",
        "trial_ends_at",
    }
)


class InvitationInvalidError(CogesError):
    """Même réponse pour un jeton inconnu, échu, révoqué, remplacé ou déjà utilisé."""

    code = "invitation_invalid"
    status_code = 400
    default_message = (
        "Ce lien d'invitation n'est plus valable. Demandez à un administrateur de vous en "
        "envoyer un nouveau."
    )


class PlatformUserExistsError(BusinessRuleError):
    code = "platform_user_exists"
    default_message = "Cette adresse a déjà un compte dans l'équipe."


class InvitationPendingError(BusinessRuleError):
    code = "invitation_pending"
    default_message = (
        "Une invitation attend déjà cette adresse : renvoyez-la ou annulez-la d'abord."
    )


class InvitationNotPendingError(BusinessRuleError):
    code = "invitation_not_pending"
    default_message = "Cette invitation a déjà été acceptée ou annulée."


class CannotModifySelfError(BusinessRuleError):
    code = "cannot_modify_self"
    default_message = (
        "Vous ne pouvez ni changer votre propre profil ni suspendre votre compte : "
        "demandez-le à un autre administrateur."
    )


class LastAdministratorError(BusinessRuleError):
    code = "last_administrator"
    default_message = (
        "Il doit toujours rester un administrateur actif. Nommez-en un autre avant de "
        "retirer celui-ci."
    )


def _new_invitation_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def invitation_url(raw_token: str) -> str:
    return f"{get_settings().admin_url.rstrip('/')}/invitation/{raw_token}"


def _member(user: PlatformUser, admin: PlatformAdmin) -> TeamMember:
    return TeamMember(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=cast(Any, user.role),
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        is_me=user.id == admin.platform_user_id,
        mfa_enabled=user.mfa_enabled_at is not None,
    )


def _invitation_read(invitation: PlatformInvitation, inviter: str) -> TeamInvitation:
    return TeamInvitation(
        id=invitation.id,
        email=invitation.email,
        display_name=invitation.display_name,
        role=cast(Any, invitation.role),
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        invited_by_name=inviter,
    )


def list_team(session: Session, admin: PlatformAdmin) -> TeamList:
    repository = TeamRepository(session)
    return TeamList(
        members=[_member(user, admin) for user in repository.members()],
        invitations=[
            _invitation_read(invitation, inviter)
            for invitation, inviter in repository.pending(datetime.now(UTC))
        ],
    )


def team_summary(session: Session) -> TeamSummary:
    now = datetime.now(UTC)
    members, active, pending, expiring = TeamRepository(session).counts(now, now + INVITATION_SOON)
    return TeamSummary(
        computed_at=now,
        members=members,
        active=active,
        suspended=members - active,
        pending_invitations=pending,
        expiring_invitations=expiring,
    )


def _deliver(session: Session, invitation: PlatformInvitation) -> str | None:
    """Fait partir le lien : par le worker après COMMIT (le jeton naît là-bas), ou, sans
    SMTP, en tirant le jeton ici pour le rendre **une fois**. Rend le lien à montrer."""
    if mailer.is_configured():
        invitation_id, issue = str(invitation.id), invitation.issue

        def _send() -> None:
            queue.enqueue(
                SEND_INVITATION_TASK, countdown=0, invitation_id=invitation_id, issue=issue
            )

        on_commit(session, _send)
        return None
    raw, token_hash = _new_invitation_token()
    invitation.token_hash = token_hash
    return invitation_url(raw)


def invite(
    session: Session,
    admin: PlatformAdmin,
    payload: InvitationCreate,
    *,
    idempotency_key: str,
    ip_address: str | None,
) -> tuple[InvitationIssued, bool]:
    """Invite un collègue. La même clé rejouée rend la même invitation, sans second envoi
    ni second lien."""
    repository = TeamRepository(session)
    existing = repository.invitation_by_key(idempotency_key)
    if existing is not None:
        same = (existing.email, existing.display_name, existing.role) == (
            payload.email,
            payload.display_name,
            payload.role,
        )
        if not same:
            raise IdempotencyKeyReusedError()
        found = repository.invitation(existing.id)
        assert found is not None
        return (
            InvitationIssued(
                invitation=_invitation_read(*found),
                email_sent=mailer.is_configured(),
                invitation_url=None,
            ),
            True,
        )
    if PlatformUserRepository(session).get_by_email(payload.email) is not None:
        raise PlatformUserExistsError()

    now = datetime.now(UTC)
    repository.revoke_lapsed(payload.email, now)
    invitation = PlatformInvitation(
        email=payload.email,
        display_name=payload.display_name,
        role=payload.role,
        idempotency_key=idempotency_key,
        invited_by=admin.platform_user_id,
        created_at=now,
        expires_at=now + INVITATION_TTL,
    )
    try:
        with session.begin_nested():
            repository.add_invitation(invitation)
    except IntegrityError as exc:
        if constraint_name(exc) == "platform_invitations_one_pending":
            raise InvitationPendingError() from exc
        raise ConcurrentUpdateError() from exc
    url = _deliver(session, invitation)
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="insert",
        entity_table="platform_invitations",
        entity_id=invitation.id,
        diff={
            "after": {
                "email": invitation.email,
                "display_name": invitation.display_name,
                "role": invitation.role,
                "expires_at": invitation.expires_at.isoformat(),
            }
        },
        ip_address=ip_address,
    )
    found = repository.invitation(invitation.id)
    assert found is not None
    return (
        InvitationIssued(
            invitation=_invitation_read(*found), email_sent=url is None, invitation_url=url
        ),
        False,
    )


def _locked_pending(repository: TeamRepository, invitation_id: UUID) -> PlatformInvitation:
    invitation = repository.lock_invitation(invitation_id)
    if invitation is None:
        raise NotFoundError("Invitation introuvable.")
    if invitation.accepted_at is not None or invitation.revoked_at is not None:
        raise InvitationNotPendingError()
    return invitation


def resend_invitation(
    session: Session, admin: PlatformAdmin, invitation_id: UUID, *, ip_address: str | None
) -> InvitationIssued:
    """Nouveau lien, 72 h de plus ; l'ancien meurt (empreinte effacée, émission suivante)."""
    repository = TeamRepository(session)
    invitation = _locked_pending(repository, invitation_id)
    invitation.issue += 1
    invitation.token_hash = None
    invitation.expires_at = datetime.now(UTC) + INVITATION_TTL
    session.flush()
    url = _deliver(session, invitation)
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="update",
        entity_table="platform_invitations",
        entity_id=invitation.id,
        diff={
            "after": {"issue": invitation.issue, "expires_at": invitation.expires_at.isoformat()}
        },
        ip_address=ip_address,
    )
    found = repository.invitation(invitation.id)
    assert found is not None
    return InvitationIssued(
        invitation=_invitation_read(*found), email_sent=url is None, invitation_url=url
    )


def revoke_invitation(
    session: Session, admin: PlatformAdmin, invitation_id: UUID, *, ip_address: str | None
) -> None:
    invitation = _locked_pending(TeamRepository(session), invitation_id)
    invitation.revoked_at = datetime.now(UTC)
    _audit(
        session,
        actor_id=admin.platform_user_id,
        action="cancel",
        entity_table="platform_invitations",
        entity_id=invitation.id,
        diff={"before": {"status": "pending"}, "after": {"status": "revoked"}},
        ip_address=ip_address,
    )


@dataclass(frozen=True, slots=True)
class InvitationMail:
    email: str
    display_name: str
    role: str
    inviter: str
    expires_at: datetime
    url: str


def issue_invitation_token(invitation_id: UUID, issue: int) -> InvitationMail | None:
    """Pour le worker : tire le jeton, en écrit l'empreinte, rend de quoi écrire l'e-mail.

    `None` si l'invitation n'attend plus ce lien : acceptée, annulée, échue, ou renvoyée
    depuis (une autre émission). Le jeton en clair ne quitte que cette fonction.
    """
    with platform_transaction() as session:
        repository = TeamRepository(session)
        invitation = repository.lock_invitation(invitation_id)
        now = datetime.now(UTC)
        if (
            invitation is None
            or invitation.issue != issue
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or invitation.expires_at <= now
        ):
            return None
        raw, token_hash = _new_invitation_token()
        invitation.token_hash = token_hash
        found = repository.invitation(invitation.id)
        assert found is not None
        return InvitationMail(
            email=invitation.email,
            display_name=invitation.display_name,
            role=invitation.role,
            inviter=found[1],
            expires_at=invitation.expires_at,
            url=invitation_url(raw),
        )


def accept_invitation(raw_token: str, password: str, *, ip_address: str | None) -> LoginStep:
    """Crée le compte et consomme le jeton (usage unique). Aucune session : le collègue
    enrôle sa double authentification d'abord (ADR 0105)."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    with platform_transaction() as session:
        repository = TeamRepository(session)
        invitation = repository.lock_invitation_by_hash(token_hash)
        now = datetime.now(UTC)
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or invitation.expires_at <= now
            or PlatformUserRepository(session).get_by_email(invitation.email) is not None
        ):
            raise InvitationInvalidError()
        user = PlatformUserRepository(session).add(
            PlatformUser(
                email=invitation.email,
                password_hash=hash_password(password),
                display_name=invitation.display_name,
                role=invitation.role,
            )
        )
        invitation.accepted_at = now
        invitation.accepted_user_id = user.id
        _audit(
            session,
            actor_id=user.id,
            action="insert",
            entity_table="platform_users",
            entity_id=user.id,
            diff={"after": {"role": user.role, "email": user.email}},
            ip_address=ip_address,
        )
        raw_challenge = _open_challenge(session, user.id, "enroll")
    return LoginStep(
        step="enroll",
        challenge_token=raw_challenge,
        expires_in=int(CHALLENGE_TTL.total_seconds()),
    )


def _check_administrators_remain(administrators: list[UUID], excluding: UUID) -> None:
    if not [user_id for user_id in administrators if user_id != excluding]:
        raise LastAdministratorError()


def assert_administrators_remain(*, excluding: UUID) -> None:
    """Refuse si retirer `excluding` ne laisse aucun administrateur actif."""
    with platform_transaction() as session:
        _check_administrators_remain(
            TeamRepository(session).lock_active_administrators(), excluding
        )


def update_member(
    session: Session,
    admin: PlatformAdmin,
    user_id: UUID,
    payload: TeamMemberUpdate,
    *,
    ip_address: str | None,
) -> TeamMember:
    """Profil ou statut d'un collègue. Jamais le sien ; toujours un administrateur actif.

    Les administrateurs actifs sont verrouillés **avant** le compte visé : deux
    administrateurs qui se retirent l'un l'autre en même temps se sérialisent, et le
    second voit qu'il ne resterait personne.
    """
    if user_id == admin.platform_user_id:
        raise CannotModifySelfError()
    repository = TeamRepository(session)
    administrators = repository.lock_active_administrators()
    member = repository.lock_member(user_id)
    if member is None:
        raise NotFoundError("Compte introuvable.")

    role = payload.role if payload.role is not None else member.role
    is_active = payload.is_active if payload.is_active is not None else member.is_active
    was_administrator = member.role == "administrator" and member.is_active
    if was_administrator and (role != "administrator" or not is_active):
        _check_administrators_remain(administrators, member.id)

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if role != member.role:
        before["role"], after["role"] = member.role, role
        member.role = role
    if is_active != member.is_active:
        before["is_active"], after["is_active"] = member.is_active, is_active
        member.is_active = is_active
    if after:
        session.flush()  # le trigger de 0026 révoque les sessions d'un compte suspendu
        diff: dict[str, Any] = {"before": before, "after": after}
        if payload.reason and payload.reason.strip():
            diff["reason"] = payload.reason.strip()
        _audit(
            session,
            actor_id=admin.platform_user_id,
            action="update",
            entity_table="platform_users",
            entity_id=member.id,
            diff=diff,
            ip_address=ip_address,
        )
    return _member(member, admin)


def list_merchant_users(
    session: Session,
    *,
    search: str | None,
    role: str | None,
    status: str | None,
    company_id: UUID | None,
    sort: str,
    page: int,
    page_size: int,
) -> MerchantUserPage:
    rows, total = MerchantUserDirectory(session).search(
        search=normalise_term(search),
        role=role,
        status=status,
        company_id=company_id,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return MerchantUserPage(
        items=[
            MerchantUser(
                id=row.id,
                full_name=row.full_name,
                email=row.email,
                company_id=row.company_id,
                company_name=row.company_name,
                roles=row.roles,
                status=(
                    "company_suspended"
                    if row.company_status == "suspended"
                    else ("active" if row.is_active else "deactivated")
                ),
                last_login_at=row.last_login_at,
            )
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


def clean_diff(value: Any) -> Any:
    """Liste blanche récursive : seules les clés connues survivent, avec des valeurs simples."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key not in AUDIT_FIELDS:
                continue
            kept = clean_diff(item)
            if kept is not _DROP:
                cleaned[key] = kept
        return cleaned
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return _DROP


_DROP = object()


def list_audit(
    session: Session,
    *,
    actor_id: UUID | None,
    action: str | None,
    company_id: UUID | None,
    entity_id: UUID | None,
    start: date | None,
    end: date | None,
    page: int,
    page_size: int,
) -> AuditPage:
    if start is not None and end is not None and start > end:
        raise PeriodInvertedError(details={"start": start.isoformat(), "end": end.isoformat()})
    zone = ZoneInfo(STATS_TIMEZONE)
    rows, total = AuditReader(session).search(
        actor_id=actor_id,
        action=action,
        company_id=company_id,
        entity_id=entity_id,
        start=datetime.combine(start, time.min, tzinfo=zone) if start else None,
        stop=datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone) if end else None,
        page=page,
        page_size=page_size,
    )
    return AuditPage(
        items=[
            AuditEntry(
                id=row.id,
                occurred_at=row.occurred_at,
                actor_id=row.actor_id,
                actor_name=row.actor_name,
                action=cast(Any, row.action),
                entity_table=row.entity_table,
                entity_id=row.entity_id,
                entity_name=row.entity_name,
                target_company_id=row.target_company_id,
                target_company_name=row.target_company_name,
                diff=clean_diff(row.diff) if isinstance(row.diff, dict) else {},
            )
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


def profiles(routes: Iterable[Any]) -> list[ProfileRead]:
    found = capabilities.capabilities(routes)
    return [
        ProfileRead(
            role=cast(Any, role),
            label=capabilities.PROFILE_TEXT[role][0],
            description=capabilities.PROFILE_TEXT[role][1],
            capabilities=[Capability(key=key, label=label) for key, label in found[role]],
        )
        for role in capabilities.PROFILES
    ]


def attention(session: Session) -> AttentionRead:
    now = datetime.now(UTC)
    repository = AttentionRepository(session)
    suspended, suspended_total = repository.suspended()
    return AttentionRead(
        computed_at=now,
        trials_ending=[
            TrialEnding(company_id=row.id, name=row.name, trial_ends_at=row.trial_ends_at)
            for row in repository.trials_ending(clock.now() + TRIAL_SOON)
        ],
        suspended_companies=[
            SuspendedCompany(company_id=row.id, name=row.name) for row in suspended
        ],
        suspended_total=suspended_total,
        reminders=len(reminders(session).items),
        expiring_invitations=[
            ExpiringInvitation(
                id=invitation.id,
                email=invitation.email,
                display_name=invitation.display_name,
                expires_at=invitation.expires_at,
            )
            for invitation in TeamRepository(session).expiring(now, now + INVITATION_SOON)
        ],
        security_events=[
            SecurityEvent(
                kind=row.kind,
                platform_user_id=row.platform_user_id,
                display_name=row.display_name,
                device=row.device,
                occurred_at=row.occurred_at,
            )
            for row in repository.security_events(now - SECURITY_EVENTS_WINDOW)
        ],
    )
