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

from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import queue, rate_limit
from app.core.audit import AuditAction, audit_critical
from app.core.config import get_settings
from app.core.deps import PlatformAdmin, platform_transaction
from app.core.errors import (
    AuthenticationRequiredError,
    BusinessRuleError,
    NotFoundError,
    ValidationFailedError,
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
from app.modules.platform.models import (
    Plan,
    PlatformAuditLog,
    PlatformAuthSession,
    PlatformUser,
    Subscription,
    SubscriptionPayment,
    SupportSession,
)
from app.modules.platform.repository import (
    CompanyDirectory,
    CompanyRow,
    PlatformAuditRepository,
    PlatformSessionRepository,
    PlatformUserRepository,
    SubscriptionRepository,
    SupportSessionRepository,
)
from app.modules.platform.schemas import (
    CompanyDetail,
    CompanyPage,
    CompanySummary,
    CompanyUser,
    PlanRead,
    PlatformMe,
    SubscriptionDetail,
    SubscriptionPaymentCreate,
    SubscriptionPaymentRead,
    SubscriptionUpdate,
    SupportAccessToken,
    SupportSessionCreate,
    SupportSessionList,
    SupportSessionRead,
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

#: Paliers d'avertissement avant la fin de l'essai, en jours.
WARNING_DAYS = (7, 3, 1)

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
        max_users=plan.max_users,
        features=list(plan.features),
        is_orderable=plan.is_orderable,
    )


def list_plans(session: Session) -> list[PlanRead]:
    return [_plan_read(plan) for plan in SubscriptionRepository(session).plans()]


def _detail(session: Session, company_id: UUID, subscription: Subscription) -> SubscriptionDetail:
    repository = SubscriptionRepository(session)
    payments, total = repository.payments(subscription.id, limit=PAYMENTS_SHOWN)
    return SubscriptionDetail(
        company_id=company_id,
        plan=_plan_read(repository.plan(subscription.plan_id)),
        status=cast(Any, subscription.status),
        trial_ends_at=subscription.trial_ends_at,
        started_at=subscription.started_at,
        current_period_end=subscription.current_period_end,
        active_users=repository.active_users(company_id),
        payments=[
            SubscriptionPaymentRead(
                id=payment.id,
                amount_fcfa=payment.amount_fcfa,
                paid_at=payment.paid_at,
                method=cast(Any, payment.method),
                note=payment.note,
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
        if plan is None or not plan.is_orderable:
            raise ValidationFailedError(
                "Cette offre n'est pas proposée.", details={"plan_code": payload.plan_code}
            )
        if plan.max_users is not None:
            active = repository.active_users(company_id)
            if active > plan.max_users:
                raise PlanDowngradeTooManyUsersError(active_users=active, max_users=plan.max_users)
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


def _next_month(moment: datetime) -> datetime:
    """Même jour le mois suivant, ramené au dernier jour s'il n'existe pas (31 → 30)."""
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    return moment.replace(year=year, month=month, day=min(moment.day, monthrange(year, month)[1]))


def record_payment(
    session: Session,
    admin: PlatformAdmin,
    company_id: UUID,
    payload: SubscriptionPaymentCreate,
    *,
    idempotency_key: str,
    ip_address: str | None = None,
) -> tuple[SubscriptionDetail, bool]:
    """Enregistre un paiement déclaré : l'abonnement devient actif, sa période avance d'un
    mois (depuis aujourd'hui, ou depuis la fin en cours si elle est plus loin), et une
    entreprise suspendue retrouve l'accès. Même clé, même paiement : rien n'est refait
    (le second élément dit si c'est un rejeu).
    """
    access, subscription = _lock(session, company_id)
    repository = SubscriptionRepository(session)
    replayed = repository.payment_by_key(idempotency_key)
    if replayed is not None:
        if replayed.subscription_id != subscription.id:
            raise IdempotencyKeyReusedError()
        return _detail(session, company_id, subscription), True

    now = datetime.now(UTC)
    payment = repository.add_payment(
        SubscriptionPayment(
            subscription_id=subscription.id,
            amount_fcfa=payload.amount_fcfa,
            paid_at=payload.paid_at,
            method=payload.method,
            note=payload.note.strip() if payload.note and payload.note.strip() else None,
            recorded_by=admin.platform_user_id,
            idempotency_key=idempotency_key,
        )
    )
    before = {
        "status": subscription.status,
        "current_period_end": _iso(subscription.current_period_end),
    }
    period_start = max(now, subscription.current_period_end or now)
    subscription.status = "active"
    subscription.current_period_end = _next_month(period_start)
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


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


# ------------------------------------------------------------- la tâche de nuit


@dataclass(frozen=True, slots=True)
class TrialNotice:
    """Ce que la tâche de nuit doit dire à une entreprise, après COMMIT."""

    company_id: UUID
    company_name: str
    #: 7, 3 ou 1 jour(s) avant la fin ; 0 : l'essai vient de se terminer.
    days: int
    trial_ends_at: datetime


def run_subscription_day(now: datetime | None = None) -> list[TrialNotice]:
    """Fin des essais : avertit à J-7, J-3, J-1, suspend à l'échéance (ADR 0091).

    Une seule transaction, sous `coges_app_platform`. Chaque palier n'est franchi qu'une
    fois (`trial_warned_days`), une entreprise n'est suspendue qu'une fois (elle quitte
    l'état `trial`) : relancer la tâche ne prévient ni ne suspend deux fois. Les messages
    partent **après** le COMMIT, par l'appelant.
    """
    moment = now or datetime.now(UTC)
    notices: list[TrialNotice] = []
    with platform_transaction() as session:
        directory = CompanyDirectory(session)
        repository = SubscriptionRepository(session)
        for company_id in repository.trials_ending_before(moment + timedelta(days=WARNING_DAYS[0])):
            access = directory.lock_status(company_id)
            subscription = repository.lock(company_id) if access else None
            if access is None or subscription is None or subscription.status != "trial":
                continue
            ends = subscription.trial_ends_at
            if ends is None:
                continue
            company = directory.get(company_id)
            name = company.name if company else ""
            if ends <= moment:
                subscription.status = "suspended"
                subscription.updated_at = moment
                session.flush()
                _audit(
                    session,
                    actor_id=None,
                    action="update",
                    entity_table="subscriptions",
                    entity_id=subscription.id,
                    target_company_id=company_id,
                    diff={
                        "before": {"status": "trial"},
                        "after": {"status": "suspended"},
                        "reason": "fin de l'essai sans paiement",
                    },
                )
                # Le gérant reçoit le message chaleureux de fin d'essai, pas celui d'une
                # suspension décidée par l'équipe.
                _set_access(
                    session,
                    company_id,
                    before=access,
                    after="suspended",
                    actor_id=None,
                    reason="fin de l'essai sans paiement",
                    notify_manager=False,
                )
                notices.append(TrialNotice(company_id, name, 0, ends))
                continue
            days_left = ceil((ends - moment) / timedelta(days=1))
            threshold = min(days for days in WARNING_DAYS if days >= days_left)
            if subscription.trial_warned_days is None or subscription.trial_warned_days > threshold:
                subscription.trial_warned_days = threshold
                subscription.updated_at = moment
                notices.append(TrialNotice(company_id, name, threshold, ends))
    return notices


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
