"""Payer 6 mois d'un coup, sans remise (prompt 44, ADR 0134).

Ajout et élargissement seuls (ADR 0083) : le code déjà en production ignore la colonne
nouvelle et n'écrit jamais 6.

- **`plans.semiannual_price_fcfa`** : prix de 6 mois, écrit ici et jamais recalculé à
  l'affichage, comme `annual_price_fcfa` (ADR 0132). 6 fois le prix du mois, sans remise :
  29 400 pour Pro, 59 400 pour Business ; `NULL` pour Premium (sur devis, montant libre).
  Il exige un prix du mois.
- **`subscription_payments.period_months`** : 1, 6 ou 12.

`plans` est lue par `GRANT SELECT` sur toute la table (révision 0028) : rien à accorder.
Le retour arrière remet l'ancien `CHECK` en `NOT VALID` : les paiements de 6 mois déjà
enregistrés sont gardés, aucun nouveau n'est accepté.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERIOD_CHECK = "subscription_payments_period_months_check"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE plans
          ADD COLUMN semiannual_price_fcfa numeric(14,2)
            CHECK (semiannual_price_fcfa >= 0),
          ADD CONSTRAINT plans_semiannual_needs_monthly
            CHECK (semiannual_price_fcfa IS NULL OR price_fcfa IS NOT NULL)
        """
    )
    op.execute("UPDATE plans SET semiannual_price_fcfa = 29400 WHERE code = 'starter'")
    op.execute("UPDATE plans SET semiannual_price_fcfa = 59400 WHERE code = 'business'")
    op.execute(
        f"""
        ALTER TABLE subscription_payments
          DROP CONSTRAINT {PERIOD_CHECK},
          ADD CONSTRAINT {PERIOD_CHECK} CHECK (period_months IN (1, 6, 12))
        """
    )


def downgrade() -> None:
    # L'ancienne règle revient pour les lignes nouvelles ; les paiements de 6 mois déjà
    # enregistrés restent tels quels (`NOT VALID` : rien n'est effacé ni réécrit).
    op.execute(
        f"""
        ALTER TABLE subscription_payments
          DROP CONSTRAINT {PERIOD_CHECK},
          ADD CONSTRAINT {PERIOD_CHECK} CHECK (period_months IN (1, 12)) NOT VALID
        """
    )
    op.execute("ALTER TABLE plans DROP COLUMN semiannual_price_fcfa")
