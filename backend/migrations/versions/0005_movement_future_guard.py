"""Un mouvement ne peut pas être daté dans le futur.

Correctif de l'ADR 0015. La fenêtre d'antidatage se mesure depuis
`max(occurred_at)` du produit : une date future saisie par erreur — un « 2027 »
au lieu de « 2026 » — devient ce maximum et **bloque le produit**. Tout mouvement
ultérieur daté de `now()` tombe alors à plus de 48 h en arrière et se fait refuser
en `CG010`, ventes comprises.

Le piège est refermé : le mouvement **inverse** que l'on écrirait pour corriger la
saisie est lui aussi daté de `now()`, donc refusé à son tour. Rien ne rattrape le
produit, ni par l'API, ni par un ajustement. Seule une intervention en base le
débloquerait — exactement ce que le journal append-only cherche à éviter.

La correction ferme la borne haute : `occurred_at` ne peut pas dépasser `now()` de
plus de **5 minutes**. La tolérance n'est pas de la complaisance, elle absorbe le
décalage d'horloge entre le serveur d'application et PostgreSQL ; une saisie
légitime n'a jamais besoin de plus.

Pourquoi une révision séparée plutôt qu'une retouche de la 0004 : la 0004 est déjà
livrable, et une migration livrée ne se réécrit pas — c'est la même règle que pour
le journal qu'elle installe.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fenêtre d'antidatage, inchangée depuis la révision 0004 (ADR 0015).
BACKDATING_WINDOW = "48 hours"

# Tolérance sur la borne haute : décalage d'horloge entre l'API et PostgreSQL.
FUTURE_TOLERANCE = "5 minutes"


def upgrade() -> None:
    # Même trigger (`t05_inv_check_backdating`), même fonction : seul le corps
    # change. Le contrôle de la borne haute passe **avant** celui de la fenêtre,
    # parce qu'une date future est une faute de saisie, pas un antidatage — et que
    # le message doit le dire.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION inv_check_backdating() RETURNS trigger AS $$
        DECLARE v_last timestamptz;
        BEGIN
           IF NEW.occurred_at > now() + interval '{FUTURE_TOLERANCE}' THEN
              RAISE EXCEPTION USING ERRCODE = 'CG011',
                 MESSAGE = format(
                    'Date dans le futur : produit %s, date demandée %s '
                    '(tolérance de {FUTURE_TOLERANCE}).',
                    NEW.product_id, NEW.occurred_at);
           END IF;

           SELECT max(occurred_at) INTO v_last FROM inventory_movements
            WHERE company_id = NEW.company_id AND product_id = NEW.product_id;
           IF v_last IS NOT NULL
              AND NEW.occurred_at < v_last - interval '{BACKDATING_WINDOW}' THEN
              RAISE EXCEPTION USING ERRCODE = 'CG010',
                 MESSAGE = format(
                    'Antidatage refusé : produit %s, dernier mouvement le %s, '
                    'date demandée %s (fenêtre de {BACKDATING_WINDOW}).',
                    NEW.product_id, v_last, NEW.occurred_at);
           END IF;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    # Restitution mot pour mot du corps posé par la révision 0004.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION inv_check_backdating() RETURNS trigger AS $$
        DECLARE v_last timestamptz;
        BEGIN
           SELECT max(occurred_at) INTO v_last FROM inventory_movements
            WHERE company_id = NEW.company_id AND product_id = NEW.product_id;
           IF v_last IS NOT NULL
              AND NEW.occurred_at < v_last - interval '{BACKDATING_WINDOW}' THEN
              RAISE EXCEPTION USING ERRCODE = 'CG010',
                 MESSAGE = format(
                    'Antidatage refusé : produit %s, dernier mouvement le %s, '
                    'date demandée %s (fenêtre de {BACKDATING_WINDOW}).',
                    NEW.product_id, v_last, NEW.occurred_at);
           END IF;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
