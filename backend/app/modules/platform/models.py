"""Modèles du module Platform : comptes et sessions de l'administration, abonnements.

Ces tables n'appartiennent à aucune entreprise, donc pas de `TenantBase` (révisions 0026
et 0028). `subscriptions` porte un `company_id` et sa RLS (T37), mais elle parle **d'**
une entreprise, sous le seul rôle de l'administration : `coges_app` n'y a aucun droit.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import ENUM, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.core.database import Base


class PlatformUser(Base):
    """Compte de l'équipe CoGes. Créé par la CLI, jamais par une route publique."""

    __tablename__ = "platform_users"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(
        ENUM("administrator", "support", name="platform_role", create_type=False)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Secret TOTP chiffré par l'API (ADR 0105), jamais en clair, jamais renvoyé.
    mfa_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Dernier pas TOTP accepté : un code ne sert qu'une fois.
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class PlatformMfaChallenge(Base):
    """Jeton intermédiaire entre le mot de passe et le code (ADR 0105) : 5 min, une fois."""

    __tablename__ = "platform_mfa_challenges"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    platform_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(Text)
    #: `enroll` : aucun secret actif, seul l'enrôlement est ouvert ; `verify` : le code.
    purpose: Mapped[str] = mapped_column(Text)
    #: Secret chiffré proposé à l'enrôlement, actif seulement après un premier code juste.
    pending_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformRecoveryCode(Base):
    """Code de secours : empreinte HMAC seulement, usage unique (ADR 0105)."""

    __tablename__ = "platform_recovery_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    platform_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    code_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformKnownDevice(Base):
    """Appareil déjà vu : empreinte d'un jeton aléatoire en cookie, et le navigateur."""

    __tablename__ = "platform_known_devices"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    platform_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(Text)
    browser: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class PlatformAuthSession(Base):
    """Refresh token rotatif de l'administration, même modèle que `auth_sessions`."""

    __tablename__ = "platform_auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    platform_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(Text)
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    #: Début de la session (mot de passe et code), gardé à chaque rotation : 12 h au plus.
    authenticated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)


class PlatformAuditLog(Base):
    """Journal critique de l'administration, append-only (SELECT et INSERT seulement)."""

    __tablename__ = "platform_audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(Text)
    entity_table: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    target_company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Plan(Base):
    """Une offre : code interne stable, nom commercial modifiable (ADR 0091)."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    price_fcfa: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    #: `None` : aucun plafond (futur palier « sur devis »).
    max_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    features: Mapped[list[str]] = mapped_column(JSONB)
    is_orderable: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Subscription(Base):
    """L'état courant de l'abonnement d'une entreprise : une ligne par entreprise."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    plan_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(
        ENUM(
            "trial",
            "active",
            "past_due",
            "suspended",
            name="subscription_status",
            create_type=False,
        )
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_warned_days: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class SubscriptionPayment(Base):
    """Paiement déclaré par l'équipe : append-only, clé d'idempotence en colonne."""

    __tablename__ = "subscription_payments"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    amount_fcfa: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    method: Mapped[str] = mapped_column(
        ENUM(
            "cash",
            "mobile_money",
            "bank_transfer",
            "card",
            "cheque",
            "offset",
            "wave",
            "orange_money",
            name="pay_method",
            create_type=False,
        )
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class SupportSession(Base):
    """Accès support encadré à une entreprise (révision 0029, ADR 0092).

    Le fait qu'un accès a eu lieu — par qui, pourquoi, quand —, rien de commercial.
    `coges_app` en lit cinq colonnes, pour sa seule entreprise (le bandeau, la relecture
    à chaque requête) ; seule l'administration ouvre et ferme.
    """

    __tablename__ = "support_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    platform_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Consentement du gérant (plus tard) ; NULL pour un bris de glace.
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class PlatformInvitation(Base):
    """Invitation d'un collègue dans l'équipe (révision 0030, ADR 0094).

    Le jeton du lien n'est jamais stocké : `token_hash` est son empreinte SHA-256, vide tant
    que le worker ne l'a pas tirée. `issue` avance à chaque renvoi : un envoi plus ancien
    encore en file ne peut plus poser son empreinte.
    """

    __tablename__ = "platform_invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(
        ENUM("administrator", "support", name="platform_role", create_type=False)
    )
    token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    idempotency_key: Mapped[str] = mapped_column(Text)
    invited_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
