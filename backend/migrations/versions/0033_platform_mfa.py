"""Double authentification obligatoire de l'administration (ADR 0105).

Aucune table de commerçant n'est touchée. Tout est réservé à `coges_app_platform`
(`coges_backup` lit, pour une sauvegarde complète) :

- **`platform_users`** : `mfa_secret` (secret TOTP **chiffré** par l'API, AES-256-GCM ; la
  base ne voit jamais le secret en clair), `mfa_enabled_at`, `mfa_last_step` (dernier pas
  accepté : un code ne sert qu'une fois). Retirer la double authentification (réinitialisation)
  révoque toutes les sessions du compte, par trigger.
- **`platform_mfa_challenges`** : le jeton intermédiaire entre le mot de passe et le code
  (empreinte seule, 5 minutes, usage unique) ; pendant l'enrôlement, il porte le secret
  chiffré en attente de confirmation.
- **`platform_recovery_codes`** : empreintes HMAC des codes de secours (usage unique,
  révoqués ensemble à la régénération).
- **`platform_known_devices`** : empreinte d'un jeton d'appareil aléatoire (cookie) et le
  navigateur, pour signaler une connexion depuis un nouvel appareil. Aucune adresse IP.
- **`platform_auth_sessions.authenticated_at`** : début de la session (plafond de 12 h).
  Les sessions ouvertes avant ce lot sont révoquées : elles n'ont pas vu de code.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "coges_app"
ANALYTICS_ROLE = "coges_analytics"
PLATFORM_ROLE = "coges_app_platform"
BACKUP_ROLE = "coges_backup"

NEW_TABLES = ("platform_mfa_challenges", "platform_recovery_codes", "platform_known_devices")


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform_users
          ADD COLUMN mfa_secret      bytea,
          ADD COLUMN mfa_enabled_at  timestamptz,
          ADD COLUMN mfa_last_step   bigint CHECK (mfa_last_step >= 0),
          ADD CONSTRAINT platform_users_mfa_coherent
            CHECK ((mfa_secret IS NULL) = (mfa_enabled_at IS NULL))
        """
    )
    # Réinitialiser la double authentification d'un compte (secret retiré ou remplacé)
    # ferme toutes ses sessions, quel que soit le chemin qui l'a fait (API ou CLI).
    op.execute(
        """
        CREATE TRIGGER platform_users_revoke_sessions_on_mfa
          AFTER UPDATE OF mfa_enabled_at ON platform_users
          FOR EACH ROW
          WHEN (OLD.mfa_enabled_at IS NOT NULL
                AND OLD.mfa_enabled_at IS DISTINCT FROM NEW.mfa_enabled_at)
          EXECUTE FUNCTION platform_users_revoke_sessions()
        """
    )

    op.execute(
        "ALTER TABLE platform_auth_sessions "
        "ADD COLUMN authenticated_at timestamptz NOT NULL DEFAULT now()"
    )
    op.execute(
        """
        UPDATE platform_auth_sessions
           SET authenticated_at = issued_at
        """
    )
    op.execute(
        """
        UPDATE platform_auth_sessions
           SET revoked_at = now()
         WHERE revoked_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TABLE platform_mfa_challenges (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          platform_user_id  uuid NOT NULL REFERENCES platform_users (id) ON DELETE CASCADE,
          token_hash        text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
          purpose           text NOT NULL CHECK (purpose IN ('enroll', 'verify')),
          pending_secret    bytea,
          created_at        timestamptz NOT NULL DEFAULT now(),
          expires_at        timestamptz NOT NULL,
          consumed_at       timestamptz,
          CONSTRAINT platform_mfa_challenges_expiry_after_creation
            CHECK (expires_at > created_at),
          CONSTRAINT platform_mfa_challenges_secret_for_enrollment
            CHECK (pending_secret IS NULL OR purpose = 'enroll')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE platform_recovery_codes (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          platform_user_id  uuid NOT NULL REFERENCES platform_users (id) ON DELETE CASCADE,
          code_hash         text NOT NULL CHECK (code_hash ~ '^[0-9a-f]{64}$'),
          created_at        timestamptz NOT NULL DEFAULT now(),
          used_at           timestamptz,
          revoked_at        timestamptz,
          CONSTRAINT platform_recovery_codes_unique UNIQUE (platform_user_id, code_hash),
          CONSTRAINT platform_recovery_codes_one_outcome
            CHECK (used_at IS NULL OR revoked_at IS NULL)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE platform_known_devices (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          platform_user_id  uuid NOT NULL REFERENCES platform_users (id) ON DELETE CASCADE,
          token_hash        text NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
          browser           text NOT NULL CHECK (length(browser) BETWEEN 1 AND 80),
          first_seen_at     timestamptz NOT NULL DEFAULT now(),
          last_seen_at      timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT platform_known_devices_unique UNIQUE (platform_user_id, token_hash)
        )
        """
    )

    for table in NEW_TABLES:
        for role in (APP_ROLE, ANALYTICS_ROLE):
            op.execute(f"REVOKE ALL ON {table} FROM {role}")
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {PLATFORM_ROLE}")
        op.execute(f"GRANT SELECT ON {table} TO {BACKUP_ROLE}")
    op.execute(
        f"GRANT UPDATE (pending_secret, consumed_at) ON platform_mfa_challenges TO {PLATFORM_ROLE}"
    )
    op.execute(f"GRANT UPDATE (used_at, revoked_at) ON platform_recovery_codes TO {PLATFORM_ROLE}")
    op.execute(f"GRANT UPDATE (last_seen_at) ON platform_known_devices TO {PLATFORM_ROLE}")


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP TABLE {table}")
    op.execute("ALTER TABLE platform_auth_sessions DROP COLUMN authenticated_at")
    op.execute("DROP TRIGGER platform_users_revoke_sessions_on_mfa ON platform_users")
    op.execute(
        """
        ALTER TABLE platform_users
          DROP CONSTRAINT platform_users_mfa_coherent,
          DROP COLUMN mfa_last_step,
          DROP COLUMN mfa_enabled_at,
          DROP COLUMN mfa_secret
        """
    )
