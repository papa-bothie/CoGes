"""Accès aux demandes d'inscription (ADR 0118).

Deux portes, jamais d'accès direct aux tables sous `coges_app` :

* sous `coges_app` (routes publiques, activation, connexion), uniquement les fonctions
  `SECURITY DEFINER` de `coges_signup` ;
* sous `coges_app_platform` (l'équipe, les tâches de fond), des requêtes qui ne nomment
  que les colonnes accordées par la révision 0039 — jamais le mot de passe haché ni
  l'empreinte de l'IP.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.sql import text


@dataclass(frozen=True, slots=True)
class CreatedRequest:
    request_id: UUID
    created: bool
    path: str


@dataclass(frozen=True, slots=True)
class ReservedRequest:
    shop_name: str
    full_name: str
    phone: str
    email: str | None
    email_verified: bool
    password_hash: str
    legal_version: str
    legal_accepted_at: datetime


@dataclass(frozen=True, slots=True)
class PendingLogin:
    password_hash: str
    path: str
    email_pending: bool


# --- Sous coges_app : les fonctions de coges_signup ---------------------------------------


def create(
    session: Session,
    *,
    shop_name: str,
    full_name: str,
    phone: str,
    email: str | None,
    password_hash: str,
    legal_version: str,
    ip_hash: str | None,
    path: str,
) -> CreatedRequest:
    row = session.execute(
        text(
            "SELECT request_id, created, path FROM signup_create("
            ":shop_name, :full_name, :phone, CAST(:email AS citext), :password_hash, "
            ":legal_version, :ip_hash, :path)"
        ),
        {
            "shop_name": shop_name,
            "full_name": full_name,
            "phone": phone,
            "email": email,
            "password_hash": password_hash,
            "legal_version": legal_version,
            "ip_hash": ip_hash,
            "path": path,
        },
    ).one()
    return CreatedRequest(request_id=row.request_id, created=row.created, path=row.path)


def issue_token(
    session: Session, request_id: UUID, token_hash: str, ttl: timedelta
) -> tuple[str, str] | None:
    """Nouveau jeton (l'ancien tombe) ; rend (e-mail, nom de la boutique) à qui écrire."""
    row = session.execute(
        text("SELECT email, shop_name FROM signup_token_issue(:id, :hash, :ttl)"),
        {"id": request_id, "hash": token_hash, "ttl": ttl},
    ).one_or_none()
    return None if row is None else (str(row.email), str(row.shop_name))


def consume_token(session: Session, token_hash: str) -> UUID | None:
    value = session.execute(
        text("SELECT signup_token_consume(:hash)"), {"hash": token_hash}
    ).scalar_one()
    return value if isinstance(value, UUID) else None


def reserve(session: Session, request_id: UUID) -> ReservedRequest | None:
    row = session.execute(
        text(
            "SELECT shop_name, full_name, phone, email, email_verified, password_hash, "
            "legal_version, legal_accepted_at FROM signup_reserve(:id)"
        ),
        {"id": request_id},
    ).one_or_none()
    if row is None:
        return None
    return ReservedRequest(
        shop_name=row.shop_name,
        full_name=row.full_name,
        phone=row.phone,
        email=None if row.email is None else str(row.email),
        email_verified=row.email_verified,
        password_hash=row.password_hash,
        legal_version=row.legal_version,
        legal_accepted_at=row.legal_accepted_at,
    )


def mark_activated(
    session: Session,
    request_id: UUID,
    company_id: UUID,
    *,
    actor: UUID | None,
    via: str,
    ip_address: str | None,
) -> bool:
    return bool(
        session.execute(
            text("SELECT signup_mark_activated(:id, :company, :actor, :via, CAST(:ip AS inet))"),
            {"id": request_id, "company": company_id, "actor": actor, "via": via, "ip": ip_address},
        ).scalar_one()
    )


def known(session: Session, *, email: str | None, phone: str | None) -> bool:
    """Vrai si un compte existe déjà avec cet e-mail ou ce numéro (forme de `users.phone`)."""
    return bool(
        session.execute(
            text("SELECT signup_known(CAST(:email AS citext), :phone)"),
            {"email": email, "phone": phone},
        ).scalar_one()
    )


def pending_for_login(
    session: Session, *, email: str | None, phone: str | None
) -> list[PendingLogin]:
    rows = session.execute(
        text(
            "SELECT password_hash, path, email_pending "
            "FROM signup_login_lookup(CAST(:email AS citext), :phone)"
        ),
        {"email": email, "phone": phone},
    ).all()
    return [
        PendingLogin(
            password_hash=row.password_hash, path=row.path, email_pending=row.email_pending
        )
        for row in rows
    ]


def resend_target(session: Session, email: str) -> UUID | None:
    value = session.execute(
        text("SELECT signup_resend_target(CAST(:email AS citext))"), {"email": email}
    ).scalar_one()
    return value if isinstance(value, UUID) else None


def switch_to_team(session: Session, email: str) -> UUID | None:
    value = session.execute(
        text("SELECT signup_switch_to_team(CAST(:email AS citext))"), {"email": email}
    ).scalar_one()
    return value if isinstance(value, UUID) else None


# --- Sous coges_app_platform : l'équipe et les tâches de fond -----------------------------

#: Colonnes lues par l'équipe : exactement celles de `PLATFORM_READ` (révision 0039).
_COLUMNS = (
    "r.id, r.shop_name, r.full_name, r.phone, r.email, r.legal_version, r.path, "
    "r.path_changed_at, r.status, r.email_verified_at, r.reject_reason, r.team_note, "
    "r.created_at, r.decided_at, r.decided_via, r.activated_company_id, r.purged_at"
)


def list_requests(
    session: Session,
    *,
    status: str | None,
    path: str | None,
    older_than: datetime | None,
    page: int,
    page_size: int,
) -> tuple[list[Any], int]:
    clauses = ["TRUE"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if status is not None:
        clauses.append("r.status = :status")
        params["status"] = status
    if path is not None:
        clauses.append("r.path = :path")
        params["path"] = path
    if older_than is not None:
        clauses.append("r.created_at < :older_than")
        params["older_than"] = older_than
    where = " AND ".join(clauses)
    rows = session.execute(
        text(
            f"SELECT {_COLUMNS}, c.slug AS company_slug FROM signup_requests r "  # noqa: S608
            "LEFT JOIN companies c ON c.id = r.activated_company_id "
            f"WHERE {where} ORDER BY r.created_at DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    ).all()
    total = session.execute(
        text(f"SELECT count(*) FROM signup_requests r WHERE {where}"),  # noqa: S608
        params,
    ).scalar_one()
    return list(rows), int(total)


def get_request(session: Session, request_id: UUID, *, lock: bool = False) -> Any | None:
    return session.execute(
        text(
            f"SELECT {_COLUMNS}, c.slug AS company_slug FROM signup_requests r "  # noqa: S608
            "LEFT JOIN companies c ON c.id = r.activated_company_id WHERE r.id = :id"
            + (" FOR UPDATE OF r" if lock else "")
        ),
        {"id": request_id},
    ).one_or_none()


def team_queue_size(session: Session) -> int:
    return int(
        session.execute(
            text("SELECT count(*) FROM signup_requests WHERE status = 'pending' AND path = 'team'")
        ).scalar_one()
    )


def known_accounts(session: Session, *, email: str | None, phone: str | None) -> list[Any]:
    """Où ce numéro ou cet e-mail ont déjà un compte (colonnes accordées à l'équipe)."""
    return list(
        session.execute(
            text(
                """
                SELECT DISTINCT c.id AS company_id, c.name AS company_name, c.slug AS company_slug,
                       CASE WHEN CAST(:phone AS text) IS NOT NULL
                                 AND u.phone = CAST(:phone AS text) THEN 'phone'
                            ELSE 'email' END AS matched_on
                  FROM users u JOIN companies c ON c.id = u.company_id
                 WHERE u.deleted_at IS NULL AND c.deleted_at IS NULL
                   AND ((CAST(:phone AS text) IS NOT NULL AND u.phone = CAST(:phone AS text))
                        OR (CAST(:email AS text) IS NOT NULL AND u.email = CAST(:email AS citext)))
                 ORDER BY c.name
                """
            ),
            {"email": email, "phone": phone},
        ).all()
    )


def reject(
    session: Session, request_id: UUID, *, actor: UUID, reason: str, note: str | None
) -> None:
    session.execute(
        text(
            """
            UPDATE signup_requests
               SET status = 'rejected', reject_reason = :reason,
                   team_note = COALESCE(:note, team_note), decided_at = now(),
                   decided_by = :actor, decided_via = 'team'
             WHERE id = :id AND status = 'pending';
            """
        ),
        {"id": request_id, "reason": reason, "note": note, "actor": actor},
    )


def set_note(session: Session, request_id: UUID, note: str) -> None:
    session.execute(
        text(
            """
            UPDATE signup_requests
               SET team_note = :note
             WHERE id = :id;
            """
        ),
        {"id": request_id, "note": note},
    )


def switch_stale_to_team(session: Session, *, after: timedelta) -> int:
    """Demande avec e-mail jamais vérifié : elle passe dans la file de l'équipe."""
    result = session.execute(
        text(
            """
            UPDATE signup_requests
               SET path = 'team', path_changed_at = now()
             WHERE status = 'pending' AND path = 'email' AND email_verified_at IS NULL
               AND created_at < now() - :after;
            """
        ),
        {"after": after},
    )
    return int(getattr(result, "rowcount", 0) or 0)


def abandon_stale(session: Session, *, after: timedelta) -> int:
    result = session.execute(
        text(
            """
            UPDATE signup_requests
               SET status = 'abandoned', decided_at = now(), decided_via = 'system'
             WHERE status = 'pending' AND path = 'team'
               AND COALESCE(path_changed_at, created_at) < now() - :after;
            """
        ),
        {"after": after},
    )
    return int(getattr(result, "rowcount", 0) or 0)


def purge_personal_data(session: Session, *, after: timedelta) -> int:
    """Refusées ou abandonnées depuis `after` : seules les statistiques restent."""
    result = session.execute(
        text(
            """
            UPDATE signup_requests
               SET shop_name = NULL, full_name = NULL, phone = NULL, email = NULL,
                   password_hash = NULL, team_note = NULL, ip_hash = NULL, purged_at = now()
             WHERE status IN ('rejected', 'abandoned')
               AND purged_at IS NULL AND decided_at < now() - :after;
            """
        ),
        {"after": after},
    )
    return int(getattr(result, "rowcount", 0) or 0)


def stats(session: Session, *, since: datetime) -> Any:
    return session.execute(
        text(
            """
            SELECT
              -- « Par chemin » : avec un e-mail (lien automatique possible) ou sans.
              -- Une demande effacée (30 jours) n'a plus d'e-mail : elle compte « sans ».
              count(*) FILTER (WHERE created_at >= :since AND email IS NOT NULL) AS received_email,
              count(*) FILTER (WHERE created_at >= :since AND email IS NULL)  AS received_team,
              count(*) FILTER (WHERE created_at >= :since
                                 AND decided_via = 'email_link')             AS activated_by_link,
              count(*) FILTER (WHERE created_at >= :since AND status = 'activated'
                                 AND decided_via = 'team')                   AS activated_by_team,
              count(*) FILTER (WHERE created_at >= :since AND status = 'rejected') AS rejected,
              count(*) FILTER (WHERE created_at >= :since AND status = 'abandoned') AS abandoned,
              count(*) FILTER (WHERE status = 'pending' AND path = 'team')   AS pending_team,
              count(*) FILTER (WHERE status = 'pending' AND path = 'email')  AS pending_email,
              avg(extract(epoch FROM decided_at - created_at) / 3600)
                FILTER (WHERE created_at >= :since AND status = 'activated') AS average_hours
            FROM signup_requests
            """
        ),
        {"since": since},
    ).one()
