"""Relances de fin d'essai et d'échéance, délai de grâce, suspension à J+3 (prompt 43, ADR 0133).

Ajout seul (ADR 0083) : le code déjà en production ignore les colonnes nouvelles.

- **`subscriptions.reminder_stage`** : dernière étape franchie pour l'échéance
  `reminder_for_end` (`eve` la veille, `due` le jour J, `last` le dernier rappel,
  `suspended` la suspension), franchie à `reminder_at` (une étape par jour au plus). Une
  échéance nouvelle (paiement, « Prolonger ») ne correspond plus à `reminder_for_end` :
  le calendrier repart de zéro. Les trois colonnes vont ensemble.
- **`trial_warned_days`** reste en base, plus lue par le code : la version précédente,
  qui tourne pendant le déploiement, l'écrit encore. À retirer dans une révision
  ultérieure.
- **`companies.timezone`** devient lisible par `coges_app_platform` : la tâche de nuit
  compte les jours dans le fuseau de l'entreprise. Une métadonnée, pas une donnée
  commerciale (ADR 0089).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLATFORM_ROLE = "coges_app_platform"
STAGES = ("eve", "due", "last", "suspended")


def upgrade() -> None:
    stages = ", ".join(f"'{stage}'" for stage in STAGES)
    op.execute(
        f"""
        ALTER TABLE subscriptions
          ADD COLUMN reminder_stage text CHECK (reminder_stage IN ({stages})),
          ADD COLUMN reminder_for_end timestamptz,
          ADD COLUMN reminder_at timestamptz,
          ADD CONSTRAINT subscriptions_reminder_together
            CHECK ((reminder_stage IS NULL) = (reminder_for_end IS NULL)
               AND (reminder_stage IS NULL) = (reminder_at IS NULL))
        """
    )
    op.execute(f"GRANT SELECT (timezone) ON companies TO {PLATFORM_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT (timezone) ON companies FROM {PLATFORM_ROLE}")
    op.execute(
        """
        ALTER TABLE subscriptions
          DROP CONSTRAINT subscriptions_reminder_together,
          DROP COLUMN reminder_at,
          DROP COLUMN reminder_for_end,
          DROP COLUMN reminder_stage
        """
    )
