"""Invitations de l'équipe CoGes, lot admin 6 (ADR 0094).

Un administrateur invite un collègue par e-mail ; le collègue choisit son mot de passe en
suivant le lien. Aucune table de commerçant n'est touchée, aucun droit nouveau sur elles.

- **`platform_invitations`** (hors RLS, sans `company_id`, comme `platform_users`) : qui est
  invité, avec quel profil, par qui, jusqu'à quand. Le jeton du lien n'est **jamais** stocké :
  seule son empreinte SHA-256 (`token_hash`), posée par le worker juste avant l'envoi (ou par
  l'API quand aucun SMTP n'est configuré). `issue` compte les émissions : un renvoi la fait
  avancer, et un envoi plus ancien encore en file ne peut plus écrire son empreinte.
- **Une seule invitation en attente par adresse** (index unique partiel) ; une invitation
  échue est révoquée par le service avant d'en créer une autre.
- `coges_app_platform` : SELECT et INSERT, UPDATE sur les seules colonnes du cycle de vie.
- Le journal de la plateforme s'interroge par acteur et par cible (écran « Journal »).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "coges_app"
ANALYTICS_ROLE = "coges_analytics"
PLATFORM_ROLE = "coges_app_platform"
BACKUP_ROLE = "coges_backup"

#: Ce qui change au fil de la vie d'une invitation ; le reste s'écrit une fois.
LIFECYCLE_COLUMNS = "token_hash, issue, expires_at, accepted_at, accepted_user_id, revoked_at"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform_invitations (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          email             citext NOT NULL
                            CHECK (email ~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'
                                   AND email = lower(email)),
          display_name      text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 120),
          role              platform_role NOT NULL,
          token_hash        text UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
          issue             integer NOT NULL DEFAULT 1 CHECK (issue >= 1),
          idempotency_key   text NOT NULL UNIQUE
                            CHECK (length(idempotency_key) BETWEEN 8 AND 255),
          invited_by        uuid NOT NULL REFERENCES platform_users (id),
          created_at        timestamptz NOT NULL DEFAULT now(),
          expires_at        timestamptz NOT NULL,
          accepted_at       timestamptz,
          accepted_user_id  uuid REFERENCES platform_users (id),
          revoked_at        timestamptz,
          CONSTRAINT platform_invitations_one_outcome
            CHECK (accepted_at IS NULL OR revoked_at IS NULL),
          CONSTRAINT platform_invitations_accepted_coherent
            CHECK ((accepted_at IS NULL) = (accepted_user_id IS NULL)),
          CONSTRAINT platform_invitations_expiry_after_creation
            CHECK (expires_at > created_at)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX platform_invitations_one_pending ON platform_invitations (email) "
        "WHERE accepted_at IS NULL AND revoked_at IS NULL"
    )

    # Les privilèges par défaut ouvrent toute table neuve à `coges_app` et
    # `coges_analytics` : on les reprend tous.
    for role in (APP_ROLE, ANALYTICS_ROLE):
        op.execute(f"REVOKE ALL ON platform_invitations FROM {role}")
    op.execute(f"GRANT SELECT, INSERT ON platform_invitations TO {PLATFORM_ROLE}")
    op.execute(f"GRANT UPDATE ({LIFECYCLE_COLUMNS}) ON platform_invitations TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT ON platform_invitations TO {BACKUP_ROLE}")

    op.execute(
        "CREATE INDEX platform_audit_logs_actor_idx "
        "ON platform_audit_logs (actor_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX platform_audit_logs_entity_idx "
        "ON platform_audit_logs (entity_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX platform_audit_logs_occurred_idx ON platform_audit_logs (occurred_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX platform_audit_logs_occurred_idx")
    op.execute("DROP INDEX platform_audit_logs_entity_idx")
    op.execute("DROP INDEX platform_audit_logs_actor_idx")
    op.execute("DROP TABLE platform_invitations")
