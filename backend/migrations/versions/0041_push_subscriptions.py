"""Notifications sur le téléphone : abonnements Web Push (prompt 36, bloc N, ADR 0120).

`push_subscriptions` : un appareil d'une personne qui a appuyé sur « Activer les
notifications ». L'adresse (`endpoint`) et les deux clés viennent du navigateur ; le
serveur chiffre chaque notification pour cet appareil (RFC 8291) et la poste à cette
adresse, chez le service de push du navigateur.

- RLS FORCE, politique tenant habituelle (T37), FK composite vers `users` (T5).
- `coges_app` n'a pas de DELETE : un abonnement **s'arrête** (`disabled_at` et sa
  raison), à la désactivation, à la déconnexion, quand le service répond 404 ou 410, ou
  quand un sixième appareil le remplace. T36 ne change pas.
- Un abonnement vivant par adresse et par entreprise (`push_subscriptions_live_uq`) :
  le même téléphone qui change de compte dans la boutique passe à la nouvelle personne.
- `coges_analytics` n'en a pas besoin.

Ajout seul, rétrocompatible (ADR 0083).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYTICS_ROLE = "coges_analytics"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE push_subscriptions (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id      uuid NOT NULL REFERENCES companies (id) ON DELETE RESTRICT,
          user_id         uuid NOT NULL,
          endpoint        text NOT NULL,
          p256dh          text NOT NULL,
          auth            text NOT NULL,
          device_label    text,
          created_at      timestamptz NOT NULL DEFAULT now(),
          updated_at      timestamptz NOT NULL DEFAULT now(),
          last_success_at timestamptz,
          failure_count   integer NOT NULL DEFAULT 0,
          disabled_at     timestamptz,
          disabled_reason text,
          CONSTRAINT push_subscriptions_tenant_uq UNIQUE (company_id, id),
          CONSTRAINT push_subscriptions_user_fk FOREIGN KEY (company_id, user_id)
            REFERENCES users (company_id, id),
          CONSTRAINT push_subscriptions_endpoint_https CHECK (
            endpoint LIKE 'https://%' AND char_length(endpoint) <= 2048
          ),
          CONSTRAINT push_subscriptions_keys_length CHECK (
            char_length(p256dh) BETWEEN 80 AND 100 AND char_length(auth) BETWEEN 16 AND 32
          ),
          CONSTRAINT push_subscriptions_label_length CHECK (char_length(device_label) <= 120),
          CONSTRAINT push_subscriptions_failures CHECK (failure_count >= 0),
          CONSTRAINT push_subscriptions_disabled_coherent CHECK (
            (disabled_at IS NULL) = (disabled_reason IS NULL)
          ),
          CONSTRAINT push_subscriptions_disabled_reason CHECK (
            disabled_reason IN ('unsubscribed', 'logout', 'gone', 'replaced', 'failures')
          )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX push_subscriptions_live_uq
            ON push_subscriptions (company_id, endpoint)
         WHERE disabled_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX push_subscriptions_user_live
            ON push_subscriptions (company_id, user_id, created_at)
         WHERE disabled_at IS NULL
        """
    )
    op.execute(
        "CREATE TRIGGER push_subscriptions_set_updated_at BEFORE UPDATE ON push_subscriptions "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute("ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE push_subscriptions FORCE  ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY push_subscriptions_tenant ON push_subscriptions
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )
    op.execute(f"REVOKE ALL ON push_subscriptions FROM {ANALYTICS_ROLE}")


def downgrade() -> None:
    op.execute("DROP TABLE push_subscriptions")
