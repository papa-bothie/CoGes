"""Correctifs de la revue de code, partie 1 (prompt 21, ADR 0087).

* **P1.1** — `outbox_release(bigint[])` rend la tentative que `outbox_claim` a consommée
  quand la publication a échoué faute de transport (Redis injoignable). Sans elle, une
  panne de quelques minutes mettait au rebut des événements sains. Propriétaire
  `coges_bus`, exécutable par le seul `coges_relay`, sur le patron
  d'`outbox_mark_published` (révision 0010).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUS_ROLE = "coges_bus"
RELAY_ROLE = "coges_relay"

RELEASE = "outbox_release(bigint[])"


def upgrade() -> None:
    _outbox_release()


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {RELEASE}")


def _outbox_release() -> None:
    # Ne touche qu'aux événements encore en attente et jamais sous zéro : un appel
    # rejoué ou tardif ne peut rien abîmer.
    op.execute(
        """
        CREATE FUNCTION outbox_release(p_ids bigint[])
        RETURNS integer
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           WITH released AS (
              UPDATE public.business_events
                 SET attempts = attempts - 1
               WHERE id = ANY(p_ids)
                 AND published_at IS NULL
                 AND attempts > 0
              RETURNING 1)
           SELECT count(*)::integer FROM released
        $fn$
        """
    )
    # Droits **avant** le transfert de propriété (révision 0010).
    op.execute(f"REVOKE ALL ON FUNCTION {RELEASE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {RELEASE} TO {RELAY_ROLE}")
    op.execute(f"GRANT CREATE ON SCHEMA public TO {BUS_ROLE}")
    op.execute(f"ALTER FUNCTION {RELEASE} OWNER TO {BUS_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {BUS_ROLE}")
