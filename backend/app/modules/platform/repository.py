"""Accès aux données du module Platform, en `coges_app_platform` seulement.

Les lectures d'entreprise sont écrites en SQL et ne nomment **que** les colonnes que la
révision 0026 accorde au rôle : demander une autre colonne, ou une autre table,
échouerait en `permission denied` — c'est voulu. Ce module n'importe ni les modèles ni
les dépôts des modules métier (dépendances vers le bas, ADR 0010) : il lit des tables
de la Plateforme, sous un rôle qui ne voit rien d'autre.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from app.modules.platform.models import (
    Plan,
    PlatformAuditLog,
    PlatformAuthSession,
    PlatformInvitation,
    PlatformUser,
    Subscription,
    SubscriptionPayment,
    SupportSession,
)

_LIKE_ESCAPE = "\\"


def _like_pattern(term: str) -> str:
    escaped = term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# Comptes vivants : ni supprimés ni désactivés ; dernière activité : la ligne d'audit la
# plus récente (index `audit_logs_actor`, une ligne par entreprise).
_SUMMARY_COLUMNS = """
    c.id, c.name, c.slug::text AS slug, c.status::text AS status, c.created_at,
    (SELECT count(*) FROM users u
      WHERE u.company_id = c.id AND u.deleted_at IS NULL AND u.is_active) AS user_count,
    (SELECT a.occurred_at FROM audit_logs a
      WHERE a.company_id = c.id ORDER BY a.occurred_at DESC LIMIT 1) AS last_activity_at
"""

_SEARCH = """
    c.deleted_at IS NULL
    AND (CAST(:pattern AS text) IS NULL
         OR c.name ILIKE :pattern ESCAPE '\\'
         OR c.slug::text ILIKE :pattern ESCAPE '\\')
    AND (CAST(:status AS text) IS NULL OR c.status::text = :status)
"""

_LIST_COMPANIES = text(
    f"SELECT {_SUMMARY_COLUMNS} FROM companies c WHERE {_SEARCH} "
    "ORDER BY c.created_at DESC, c.id LIMIT :limit OFFSET :offset"
)
_COUNT_COMPANIES = text(f"SELECT count(*) FROM companies c WHERE {_SEARCH}")
_GET_COMPANY = text(
    f"SELECT {_SUMMARY_COLUMNS} FROM companies c WHERE c.id = :id AND c.deleted_at IS NULL"
)
_LOCK_COMPANY = text(
    "SELECT c.id, c.status::text AS status FROM companies c "
    "WHERE c.id = :id AND c.deleted_at IS NULL FOR UPDATE"
)
_SET_STATUS = text(
    """
    UPDATE companies SET status = CAST(:status AS company_status) WHERE id = :id
    """
)
_COMPANY_USERS = text(
    """
    SELECT u.id, u.full_name, u.is_active, u.last_login_at,
           COALESCE(array_agg(r.name ORDER BY r.name) FILTER (WHERE r.name IS NOT NULL),
                    ARRAY[]::text[]) AS roles
    FROM users u
    LEFT JOIN user_roles ur ON ur.company_id = u.company_id AND ur.user_id = u.id
    LEFT JOIN roles r ON r.company_id = ur.company_id AND r.id = ur.role_id
    WHERE u.company_id = :id AND u.deleted_at IS NULL
    GROUP BY u.id, u.full_name, u.is_active, u.last_login_at
    ORDER BY u.full_name, u.id
    """
)


@dataclass(frozen=True, slots=True)
class CompanyRow:
    id: UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    user_count: int
    last_activity_at: datetime | None


@dataclass(frozen=True, slots=True)
class CompanyUserRow:
    id: UUID
    full_name: str
    is_active: bool
    last_login_at: datetime | None
    roles: list[str]


def _company(row: Any) -> CompanyRow:
    return CompanyRow(
        id=row.id,
        name=row.name,
        slug=row.slug,
        status=row.status,
        created_at=row.created_at,
        user_count=int(row.user_count),
        last_activity_at=row.last_activity_at,
    )


class CompanyDirectory:
    """Métadonnées des entreprises, toutes entreprises confondues."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def search(
        self, *, search: str | None, page: int, page_size: int, status: str | None = None
    ) -> tuple[list[CompanyRow], int]:
        params = {"pattern": _like_pattern(search) if search else None, "status": status}
        total = int(self.session.execute(_COUNT_COMPANIES, params).scalar_one())
        rows = self.session.execute(
            _LIST_COMPANIES, {**params, "limit": page_size, "offset": (page - 1) * page_size}
        ).all()
        return [_company(row) for row in rows], total

    def get(self, company_id: UUID) -> CompanyRow | None:
        row = self.session.execute(_GET_COMPANY, {"id": company_id}).one_or_none()
        return None if row is None else _company(row)

    def lock_status(self, company_id: UUID) -> str | None:
        """Statut actuel, ligne verrouillée jusqu'au COMMIT (deux gestes ne se croisent pas)."""
        row = self.session.execute(_LOCK_COMPANY, {"id": company_id}).one_or_none()
        return None if row is None else str(row.status)

    def set_status(self, company_id: UUID, status: str) -> None:
        self.session.execute(_SET_STATUS, {"id": company_id, "status": status})

    def users(self, company_id: UUID) -> list[CompanyUserRow]:
        return [
            CompanyUserRow(
                id=row.id,
                full_name=row.full_name,
                is_active=row.is_active,
                last_login_at=row.last_login_at,
                roles=list(row.roles),
            )
            for row in self.session.execute(_COMPANY_USERS, {"id": company_id}).all()
        ]


class PlatformUserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, platform_user_id: UUID) -> PlatformUser | None:
        return self.session.get(PlatformUser, platform_user_id)

    def get_by_email(self, email: str) -> PlatformUser | None:
        stmt = select(PlatformUser).where(PlatformUser.email == email)
        return self.session.execute(stmt).scalar_one_or_none()

    def add(self, user: PlatformUser) -> PlatformUser:
        self.session.add(user)
        self.session.flush()
        return user


class PlatformSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, auth_session: PlatformAuthSession) -> PlatformAuthSession:
        self.session.add(auth_session)
        self.session.flush()
        return auth_session

    def get_by_token_hash(self, token_hash: str) -> PlatformAuthSession | None:
        stmt = select(PlatformAuthSession).where(PlatformAuthSession.token_hash == token_hash)
        return self.session.execute(stmt).scalar_one_or_none()

    def lock_by_token_hash(self, token_hash: str) -> PlatformAuthSession | None:
        """Verrou jusqu'au COMMIT : deux rafraîchissements du même jeton se sérialisent."""
        stmt = (
            select(PlatformAuthSession)
            .where(PlatformAuthSession.token_hash == token_hash)
            .with_for_update()
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def lock_by_id(self, session_id: UUID) -> PlatformAuthSession | None:
        stmt = (
            select(PlatformAuthSession)
            .where(PlatformAuthSession.id == session_id)
            .with_for_update()
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def revoke_family(self, family_id: UUID) -> int:
        statement = (
            update(PlatformAuthSession)
            .where(
                PlatformAuthSession.family_id == family_id,
                PlatformAuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        return int(self.session.execute(statement).rowcount or 0)  # type: ignore[attr-defined]


class PlatformAuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entry: PlatformAuditLog) -> None:
        self.session.add(entry)
        self.session.flush()


# ------------------------------------------------------------ abonnements (ADR 0091)

_ACTIVE_USERS = text(
    "SELECT count(*) FROM users u WHERE u.company_id = :id AND u.is_active AND u.deleted_at IS NULL"
)


class SubscriptionRepository:
    """Offres, abonnements et paiements déclarés, sous `coges_app_platform`.

    Ordre des verrous, partout : l'entreprise (`CompanyDirectory.lock_status`), puis son
    abonnement. La tâche de nuit et un geste de l'équipe ne se croisent pas.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def plans(self) -> list[Plan]:
        return list(
            self.session.scalars(
                select(Plan).order_by(Plan.price_fcfa.asc().nulls_last(), Plan.code)
            )
        )

    def plan(self, plan_id: UUID) -> Plan:
        return self.session.get_one(Plan, plan_id)

    def plan_by_code(self, code: str) -> Plan | None:
        return self.session.scalars(select(Plan).where(Plan.code == code)).one_or_none()

    def get(self, company_id: UUID) -> Subscription | None:
        return self.session.scalars(
            select(Subscription).where(Subscription.company_id == company_id)
        ).one_or_none()

    def lock(self, company_id: UUID) -> Subscription | None:
        return self.session.scalars(
            select(Subscription).where(Subscription.company_id == company_id).with_for_update()
        ).one_or_none()

    def active_users(self, company_id: UUID) -> int:
        return int(self.session.execute(_ACTIVE_USERS, {"id": company_id}).scalar_one())

    def payments(
        self, subscription_id: UUID, *, limit: int
    ) -> tuple[list[SubscriptionPayment], int]:
        where = SubscriptionPayment.subscription_id == subscription_id
        total = int(
            self.session.scalar(select(func.count()).select_from(SubscriptionPayment).where(where))
            or 0
        )
        rows = self.session.scalars(
            select(SubscriptionPayment)
            .where(where)
            .order_by(SubscriptionPayment.paid_at.desc(), SubscriptionPayment.id)
            .limit(limit)
        )
        return list(rows), total

    def payment_by_key(self, key: str) -> SubscriptionPayment | None:
        return self.session.scalars(
            select(SubscriptionPayment).where(SubscriptionPayment.idempotency_key == key)
        ).one_or_none()

    def add_payment(self, payment: SubscriptionPayment) -> SubscriptionPayment:
        self.session.add(payment)
        self.session.flush()
        return payment

    def trials_ending_before(self, moment: datetime) -> list[UUID]:
        """Entreprises dont l'essai finit avant `moment`, les plus proches d'abord.

        Sans verrou : la tâche de nuit verrouille ensuite chaque entreprise **puis** son
        abonnement, dans l'ordre de tous les autres gestes, et revérifie.
        """
        return list(
            self.session.scalars(
                select(Subscription.company_id)
                .where(Subscription.status == "trial", Subscription.trial_ends_at <= moment)
                .order_by(Subscription.trial_ends_at, Subscription.id)
            )
        )


class SupportSessionRepository:
    """Sessions d'accès support (ADR 0092), sous `coges_app_platform`.

    Aucun verrou sur `companies` : l'ouverture écrit aussi le journal de l'entreprise, sur
    une autre connexion, avant que celle-ci ne valide. Deux ouvertures simultanées pour
    la même entreprise se départagent par l'index unique `support_sessions_one_open`.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, support_session: SupportSession) -> SupportSession:
        self.session.add(support_session)
        self.session.flush()
        return support_session

    def lock(self, session_id: UUID) -> SupportSession | None:
        return self.session.scalars(
            select(SupportSession).where(SupportSession.id == session_id).with_for_update()
        ).one_or_none()

    def open_for(self, company_id: UUID) -> SupportSession | None:
        """La session non fermée de l'entreprise (échue ou non) : au plus une."""
        return self.session.scalars(
            select(SupportSession).where(
                SupportSession.company_id == company_id, SupportSession.ended_at.is_(None)
            )
        ).one_or_none()

    def recent(self, company_id: UUID, *, limit: int) -> list[tuple[SupportSession, str]]:
        """Les dernières sessions de l'entreprise, avec le nom de qui les a ouvertes."""
        rows = self.session.execute(
            select(SupportSession, PlatformUser.display_name)
            .join(PlatformUser, PlatformUser.id == SupportSession.platform_user_id)
            .where(SupportSession.company_id == company_id)
            .order_by(SupportSession.started_at.desc(), SupportSession.id)
            .limit(limit)
        ).all()
        return [(row[0], str(row[1])) for row in rows]

    def close_expired(self, now: datetime, *, company_id: UUID | None = None) -> list[UUID]:
        """Ferme à leur échéance les sessions échues restées ouvertes ; rend leurs ids."""
        statement = (
            update(SupportSession)
            .where(SupportSession.ended_at.is_(None), SupportSession.expires_at <= now)
            .values(ended_at=SupportSession.expires_at)
            .returning(SupportSession.id)
        )
        if company_id is not None:
            statement = statement.where(SupportSession.company_id == company_id)
        return list(self.session.scalars(statement))


# ---------------------------------------------------------- statistiques (ADR 0093)

# Une seule requête : un seul instantané, donc des chiffres qui se recoupent même si une
# entreprise naît ou change de statut pendant la lecture (statuts = total = offres).
_OVERVIEW = text(
    """
    WITH live AS (
        SELECT c.id, c.status::text AS status FROM companies c WHERE c.deleted_at IS NULL
    ), subs AS (
        SELECT l.id, s.plan_id, s.status::text AS status
        FROM live l LEFT JOIN subscriptions s ON s.company_id = l.id
    )
    SELECT
        (SELECT count(*) FILTER (WHERE status = 'trial') FROM live) AS trial,
        (SELECT count(*) FILTER (WHERE status = 'active') FROM live) AS active,
        (SELECT count(*) FILTER (WHERE status = 'suspended') FROM live) AS suspended,
        (SELECT count(*) FROM live) AS total,
        (SELECT count(*) FROM users u JOIN live l ON l.id = u.company_id
          WHERE u.is_active AND u.deleted_at IS NULL) AS active_users,
        (SELECT count(*) FROM subs WHERE plan_id IS NULL) AS without_subscription,
        (SELECT coalesce(json_agg(row_to_json(p) ORDER BY p.price_fcfa NULLS LAST, p.code), '[]')
           FROM (SELECT pl.code, pl.name, pl.price_fcfa,
                        count(su.id) FILTER (WHERE su.status = 'trial') AS trial,
                        count(su.id) FILTER (WHERE su.status IN ('active', 'past_due')) AS paying,
                        count(su.id) FILTER (WHERE su.status = 'suspended') AS suspended,
                        count(su.id) AS total
                 FROM plans pl LEFT JOIN subs su ON su.plan_id = pl.id
                 GROUP BY pl.id) p) AS plans
    """
)
_REVENUE = text(
    "SELECT coalesce(sum(amount_fcfa), 0) AS total, count(*) AS payments "
    "FROM subscription_payments WHERE paid_at >= :start AND paid_at < :stop"
)
_SIGNUPS = text(
    """
    SELECT date_trunc(:unit, c.created_at AT TIME ZONE :zone)::date AS bucket, count(*) AS n
    FROM companies c
    WHERE c.deleted_at IS NULL AND c.created_at >= :since
    GROUP BY 1
    """
)


@dataclass(frozen=True, slots=True)
class OverviewRow:
    trial: int
    active: int
    suspended: int
    total: int
    active_users: int
    without_subscription: int
    plans: list[dict[str, Any]]


class StatsRepository:
    """Comptes de toute la plateforme, sous `coges_app_platform` : des colonnes déjà
    accordées (révisions 0026 et 0028), aucun droit de plus."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def overview(self) -> OverviewRow:
        row = self.session.execute(_OVERVIEW).one()
        return OverviewRow(
            trial=int(row.trial),
            active=int(row.active),
            suspended=int(row.suspended),
            total=int(row.total),
            active_users=int(row.active_users),
            without_subscription=int(row.without_subscription),
            plans=list(row.plans),
        )

    def revenue(self, start: datetime, stop: datetime) -> tuple[Decimal, int]:
        """Paiements déclarés de `start` (compris) à `stop` (exclu)."""
        row = self.session.execute(_REVENUE, {"start": start, "stop": stop}).one()
        return Decimal(row.total), int(row.payments)

    def signups(self, *, unit: str, zone: str, since: datetime) -> dict[date, int]:
        """Créations par mois ou par semaine (lundi), dans le fuseau donné."""
        rows = self.session.execute(_SIGNUPS, {"unit": unit, "zone": zone, "since": since})
        return {row.bucket: int(row.n) for row in rows}


# ------------------------------------------------------- équipe et accès (ADR 0094)


class TeamRepository:
    """Comptes de l'équipe et leurs invitations (tables de la plateforme seulement)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def members(self) -> list[PlatformUser]:
        return list(
            self.session.scalars(
                select(PlatformUser).order_by(PlatformUser.display_name, PlatformUser.id)
            )
        )

    def lock_member(self, user_id: UUID) -> PlatformUser | None:
        return self.session.scalars(
            select(PlatformUser).where(PlatformUser.id == user_id).with_for_update()
        ).one_or_none()

    def lock_active_administrators(self) -> list[UUID]:
        """Verrouille les administrateurs actifs, toujours **avant** le compte visé : deux
        administrateurs qui se retirent l'un l'autre se sérialisent ici."""
        return list(
            self.session.scalars(
                select(PlatformUser.id)
                .where(PlatformUser.role == "administrator", PlatformUser.is_active.is_(True))
                .order_by(PlatformUser.id)
                .with_for_update()
            )
        )

    def pending(self, now: datetime) -> list[tuple[PlatformInvitation, str]]:
        rows = self.session.execute(
            select(PlatformInvitation, PlatformUser.display_name)
            .join(PlatformUser, PlatformUser.id == PlatformInvitation.invited_by)
            .where(_pending(now))
            .order_by(PlatformInvitation.created_at.desc(), PlatformInvitation.id)
        ).all()
        return [(row[0], str(row[1])) for row in rows]

    def invitation(self, invitation_id: UUID) -> tuple[PlatformInvitation, str] | None:
        row = self.session.execute(
            select(PlatformInvitation, PlatformUser.display_name)
            .join(PlatformUser, PlatformUser.id == PlatformInvitation.invited_by)
            .where(PlatformInvitation.id == invitation_id)
        ).one_or_none()
        return None if row is None else (row[0], str(row[1]))

    def lock_invitation(self, invitation_id: UUID) -> PlatformInvitation | None:
        return self.session.scalars(
            select(PlatformInvitation)
            .where(PlatformInvitation.id == invitation_id)
            .with_for_update()
        ).one_or_none()

    def lock_invitation_by_hash(self, token_hash: str) -> PlatformInvitation | None:
        return self.session.scalars(
            select(PlatformInvitation)
            .where(PlatformInvitation.token_hash == token_hash)
            .with_for_update()
        ).one_or_none()

    def invitation_by_key(self, key: str) -> PlatformInvitation | None:
        return self.session.scalars(
            select(PlatformInvitation).where(PlatformInvitation.idempotency_key == key)
        ).one_or_none()

    def revoke_lapsed(self, email: str, now: datetime) -> int:
        """Révoque l'invitation échue de cette adresse : elle fait place à une nouvelle."""
        statement = (
            update(PlatformInvitation)
            .where(
                PlatformInvitation.email == email,
                PlatformInvitation.accepted_at.is_(None),
                PlatformInvitation.revoked_at.is_(None),
                PlatformInvitation.expires_at <= now,
            )
            .values(revoked_at=now)
        )
        return int(self.session.execute(statement).rowcount or 0)  # type: ignore[attr-defined]

    def add_invitation(self, invitation: PlatformInvitation) -> PlatformInvitation:
        self.session.add(invitation)
        self.session.flush()
        return invitation

    def counts(self, now: datetime, soon: datetime) -> tuple[int, int, int, int]:
        """Comptes, actifs, invitations en attente, dont celles qui échoient avant `soon`."""
        members, active = self.session.execute(
            select(
                func.count(),
                func.count().filter(PlatformUser.is_active.is_(True)),
            ).select_from(PlatformUser)
        ).one()
        pending, expiring = self.session.execute(
            select(
                func.count(),
                func.count().filter(PlatformInvitation.expires_at <= soon),
            )
            .select_from(PlatformInvitation)
            .where(_pending(now))
        ).one()
        return int(members), int(active), int(pending), int(expiring)

    def expiring(self, now: datetime, soon: datetime) -> list[PlatformInvitation]:
        return list(
            self.session.scalars(
                select(PlatformInvitation)
                .where(_pending(now), PlatformInvitation.expires_at <= soon)
                .order_by(PlatformInvitation.expires_at, PlatformInvitation.id)
            )
        )


def _pending(now: datetime) -> Any:
    return (
        PlatformInvitation.accepted_at.is_(None)
        & PlatformInvitation.revoked_at.is_(None)
        & (PlatformInvitation.expires_at > now)
    )


# Comptes commerçants en lecture seule : les colonnes de `users`, `companies`, `roles` et
# `user_roles` accordées par 0026, rien d'autre (ni téléphone, ni hachage).
_MERCHANT_USERS_WHERE = """
    u.deleted_at IS NULL AND c.deleted_at IS NULL
    AND (CAST(:pattern AS text) IS NULL
         OR u.full_name ILIKE :pattern ESCAPE '\\'
         OR u.email ILIKE :pattern ESCAPE '\\'
         OR c.name ILIKE :pattern ESCAPE '\\')
    AND (CAST(:company_id AS uuid) IS NULL OR u.company_id = :company_id)
    AND (CAST(:role AS text) IS NULL OR EXISTS (
         SELECT 1 FROM user_roles ur JOIN roles r
           ON r.company_id = ur.company_id AND r.id = ur.role_id
         WHERE ur.company_id = u.company_id AND ur.user_id = u.id AND r.name = :role))
    AND (CAST(:status AS text) IS NULL
         OR (:status = 'company_suspended' AND c.status = 'suspended')
         OR (:status = 'active' AND c.status <> 'suspended' AND u.is_active)
         OR (:status = 'deactivated' AND c.status <> 'suspended' AND NOT u.is_active))
"""
_MERCHANT_USERS_ORDER = {
    "name": "u.full_name ASC, u.id",
    "-name": "u.full_name DESC, u.id",
    "last_login": "u.last_login_at ASC NULLS LAST, u.full_name, u.id",
    "-last_login": "u.last_login_at DESC NULLS LAST, u.full_name, u.id",
}


@dataclass(frozen=True, slots=True)
class MerchantUserRow:
    id: UUID
    full_name: str
    email: str | None
    company_id: UUID
    company_name: str
    company_status: str
    is_active: bool
    last_login_at: datetime | None
    roles: list[str]


class MerchantUserDirectory:
    """Les comptes des commerçants, toutes entreprises, **en lecture seule**."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def search(
        self,
        *,
        search: str | None,
        role: str | None,
        status: str | None,
        company_id: UUID | None,
        sort: str,
        page: int,
        page_size: int,
    ) -> tuple[list[MerchantUserRow], int]:
        params: dict[str, Any] = {
            "pattern": _like_pattern(search) if search else None,
            "role": role,
            "status": status,
            "company_id": company_id,
        }
        base = f"FROM users u JOIN companies c ON c.id = u.company_id WHERE {_MERCHANT_USERS_WHERE}"
        total = int(self.session.execute(text(f"SELECT count(*) {base}"), params).scalar_one())
        rows = self.session.execute(
            text(
                f"""
                SELECT u.id, u.full_name, u.email, u.company_id, c.name AS company_name,
                       c.status::text AS company_status, u.is_active, u.last_login_at,
                       ARRAY(SELECT r.name FROM user_roles ur JOIN roles r
                               ON r.company_id = ur.company_id AND r.id = ur.role_id
                             WHERE ur.company_id = u.company_id AND ur.user_id = u.id
                             ORDER BY r.name) AS roles
                {base}
                ORDER BY {_MERCHANT_USERS_ORDER[sort]}
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        ).all()
        return [
            MerchantUserRow(
                id=row.id,
                full_name=row.full_name,
                email=row.email,
                company_id=row.company_id,
                company_name=row.company_name,
                company_status=row.company_status,
                is_active=row.is_active,
                last_login_at=row.last_login_at,
                roles=list(row.roles),
            )
            for row in rows
        ], total


_AUDIT_WHERE = """
    (CAST(:actor_id AS uuid) IS NULL OR a.actor_id = :actor_id)
    AND (CAST(:action AS text) IS NULL OR a.action = :action)
    AND (CAST(:company_id AS uuid) IS NULL OR a.target_company_id = :company_id)
    AND (CAST(:entity_id AS uuid) IS NULL OR a.entity_id = :entity_id)
    AND (CAST(:start AS timestamptz) IS NULL OR a.occurred_at >= :start)
    AND (CAST(:stop AS timestamptz) IS NULL OR a.occurred_at < :stop)
"""


@dataclass(frozen=True, slots=True)
class AuditRow:
    id: int
    occurred_at: datetime
    actor_id: UUID | None
    actor_name: str | None
    action: str
    entity_table: str
    entity_id: UUID | None
    entity_name: str | None
    target_company_id: UUID | None
    target_company_name: str | None
    diff: Any


class AuditReader:
    """Le journal de la plateforme, avec le nom de l'acteur, de la cible et de l'entreprise."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def search(
        self,
        *,
        actor_id: UUID | None,
        action: str | None,
        company_id: UUID | None,
        entity_id: UUID | None,
        start: datetime | None,
        stop: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditRow], int]:
        params: dict[str, Any] = {
            "actor_id": actor_id,
            "action": action,
            "company_id": company_id,
            "entity_id": entity_id,
            "start": start,
            "stop": stop,
        }
        total = int(
            self.session.execute(
                text(f"SELECT count(*) FROM platform_audit_logs a WHERE {_AUDIT_WHERE}"), params
            ).scalar_one()
        )
        rows = self.session.execute(
            text(
                f"""
                SELECT a.id, a.occurred_at, a.actor_id, actor.display_name AS actor_name,
                       a.action, a.entity_table, a.entity_id,
                       CASE a.entity_table
                         WHEN 'platform_users' THEN
                           (SELECT p.display_name FROM platform_users p WHERE p.id = a.entity_id)
                         WHEN 'platform_invitations' THEN
                           (SELECT i.display_name FROM platform_invitations i
                             WHERE i.id = a.entity_id)
                       END AS entity_name,
                       a.target_company_id, c.name AS target_company_name, a.diff
                FROM platform_audit_logs a
                LEFT JOIN platform_users actor ON actor.id = a.actor_id
                LEFT JOIN companies c ON c.id = a.target_company_id
                WHERE {_AUDIT_WHERE}
                ORDER BY a.occurred_at DESC, a.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        ).all()
        return [
            AuditRow(
                id=int(row.id),
                occurred_at=row.occurred_at,
                actor_id=row.actor_id,
                actor_name=row.actor_name,
                action=row.action,
                entity_table=row.entity_table,
                entity_id=row.entity_id,
                entity_name=row.entity_name,
                target_company_id=row.target_company_id,
                target_company_name=row.target_company_name,
                diff=row.diff,
            )
            for row in rows
        ], total


_TRIALS_ENDING = text(
    """
    SELECT c.id, c.name, s.trial_ends_at
    FROM subscriptions s JOIN companies c ON c.id = s.company_id
    WHERE c.deleted_at IS NULL AND s.status = 'trial' AND s.trial_ends_at <= :until
    ORDER BY s.trial_ends_at, c.id
    LIMIT 50
    """
)
_SUSPENDED = text(
    """
    SELECT c.id, c.name, count(*) OVER () AS total
    FROM companies c
    WHERE c.deleted_at IS NULL AND c.status = 'suspended'
    ORDER BY c.created_at DESC, c.id
    LIMIT 20
    """
)


class AttentionRepository:
    """Ce qui demande une action : essais qui finissent, entreprises suspendues."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def trials_ending(self, until: datetime) -> list[Any]:
        return list(self.session.execute(_TRIALS_ENDING, {"until": until}).all())

    def suspended(self) -> tuple[list[Any], int]:
        rows = list(self.session.execute(_SUSPENDED).all())
        return rows, int(rows[0].total) if rows else 0
