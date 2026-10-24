"""Accès aux données du module Platform, en `coges_app_platform` seulement.

Les lectures d'entreprise sont écrites en SQL et ne nomment **que** les colonnes que la
révision 0026 accorde au rôle : demander une autre colonne, ou une autre table,
échouerait en `permission denied` — c'est voulu. Ce module n'importe ni les modèles ni
les dépôts des modules métier (dépendances vers le bas, ADR 0010) : il lit des tables
de la Plateforme, sous un rôle qui ne voit rien d'autre.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from app.modules.platform.models import (
    Plan,
    PlatformAuditLog,
    PlatformAuthSession,
    PlatformUser,
    Subscription,
    SubscriptionPayment,
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
        self, *, search: str | None, page: int, page_size: int
    ) -> tuple[list[CompanyRow], int]:
        params = {"pattern": _like_pattern(search) if search else None}
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
