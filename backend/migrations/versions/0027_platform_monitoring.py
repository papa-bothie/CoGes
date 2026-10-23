"""Surveillance de la plateforme en version web, lot admin 2 (ADR 0090).

L'administration lit ce que `/system/workers` lisait déjà, plus l'historique des tâches
et le rebut de l'outbox. Toujours par des fonctions `SECURITY DEFINER`, jamais par un
GRANT sur une table : `job_runs` reste fermée, `business_events` reste une table
commerciale sans aucun droit pour `coges_app_platform`.

- **`job_runs_history`** (`coges_ops`) : les exécutions des 90 derniers jours (la durée
  de `purge_job_runs`), filtrables par tâche et par statut, paginées. Une exécution
  restée `running` au-delà du délai est un échec, comme dans `job_runs_latest`. Rend
  `per_company` (sous-tâche d'une entreprise ou non), **jamais** le `company_id`.
- **`outbox_dead_letters`** (`coges_bus`) : les événements au rebut, avec ce qu'il faut
  pour les rejouer à la main (identifiant, type, date, tentatives). **Jamais** le
  `payload`, qui porte des données commerciales, ni le `company_id`.
- **Liste blanche** : `coges_app_platform` reçoit EXECUTE sur ces deux fonctions et sur
  `outbox_lag()` et `job_runs_latest(interval)`, et sur rien d'autre
  (`tests/tenancy/test_platform_role_grants.py`). `coges_app` ne gagne rien.

Aucun nouveau rôle : rien à lancer sur Neon avant cette révision.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLATFORM_ROLE = "coges_app_platform"
OPS_ROLE = "coges_ops"
BUS_ROLE = "coges_bus"

HISTORY = "job_runs_history(text, text, interval, integer, integer)"
DEAD_LETTERS = "outbox_dead_letters(integer, integer)"

#: Fonctions existantes (révision 0021) ouvertes à l'administration.
EXISTING_FUNCTIONS = ((BUS_ROLE, "outbox_lag()"), (OPS_ROLE, "job_runs_latest(interval)"))


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION job_runs_history(p_job text, p_status text, p_stale interval,
                                         p_limit integer, p_offset integer)
        RETURNS TABLE (id bigint, job text, status text, started_at timestamptz,
                       finished_at timestamptz, error text, per_company boolean,
                       total bigint)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           WITH runs AS (
              SELECT r.id, r.job, r.started_at, r.finished_at, r.error::text AS error,
                     r.company_id IS NOT NULL AS per_company,
                     CASE WHEN r.status = 'running' AND r.started_at < now() - p_stale
                          THEN 'failed' ELSE r.status::text END AS status
                FROM public.job_runs r
               WHERE r.started_at > now() - interval '90 days'
                 AND (p_job IS NULL OR r.job = p_job)
           )
           SELECT runs.id, runs.job, runs.status, runs.started_at, runs.finished_at,
                  runs.error, runs.per_company, count(*) OVER ()
             FROM runs
            WHERE p_status IS NULL OR runs.status = p_status
            ORDER BY runs.started_at DESC, runs.id DESC
            LIMIT p_limit OFFSET p_offset
        $fn$
        """
    )
    # Même seuil que `outbox_lag()` : 10 tentatives, porté aussi par le CHECK de la table.
    op.execute(
        """
        CREATE FUNCTION outbox_dead_letters(p_limit integer, p_offset integer)
        RETURNS TABLE (id bigint, event_type text, occurred_at timestamptz, attempts integer,
                       total bigint)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           SELECT e.id, e.event_type::text, e.occurred_at, e.attempts::integer,
                  count(*) OVER ()
             FROM public.business_events e
            WHERE e.published_at IS NULL AND e.attempts >= 10
            ORDER BY e.occurred_at, e.id
            LIMIT p_limit OFFSET p_offset
        $fn$
        """
    )

    # Droits d'exécution **avant** le transfert de propriété (même raison qu'en 0021).
    for signature in (HISTORY, DEAD_LETTERS):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {PLATFORM_ROLE}")

    for owner, signature in ((OPS_ROLE, HISTORY), (BUS_ROLE, DEAD_LETTERS)):
        op.execute(f"GRANT CREATE ON SCHEMA public TO {owner}")
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {owner}")
        op.execute(f"REVOKE CREATE ON SCHEMA public FROM {owner}")

    # Les fonctions de 0021 appartiennent déjà à leur rôle, dont `coges_owner` est membre
    # sans hériter : un GRANT de sa part serait un no-op silencieux. On le fait en leur nom.
    _as_owner(grant=True)


def _as_owner(*, grant: bool) -> None:
    verb = "GRANT EXECUTE ON FUNCTION {} TO" if grant else "REVOKE EXECUTE ON FUNCTION {} FROM"
    for owner, signature in EXISTING_FUNCTIONS:
        op.execute(f"SET LOCAL ROLE {owner}")
        op.execute(f"{verb.format(signature)} {PLATFORM_ROLE}")
        op.execute("RESET ROLE")


def downgrade() -> None:
    _as_owner(grant=False)
    op.execute(f"DROP FUNCTION IF EXISTS {DEAD_LETTERS}")
    op.execute(f"DROP FUNCTION IF EXISTS {HISTORY}")
