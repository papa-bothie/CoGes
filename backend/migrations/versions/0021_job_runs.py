"""Journal des tâches planifiées et lecture de l'outbox pour la surveillance (ADR 0077).

Savoir en moins de dix minutes qu'un batch de nuit n'a pas tourné exige une trace de
chaque exécution. Elle vit dans `job_runs`, table de plate-forme absente du § 8 —
écart assumé et consigné dans l'ADR 0077.

- **Qui lit, qui écrit** : personne directement. `coges_app` (worker et API),
  `coges_relay` et `coges_analytics` n'ont **aucun** privilège sur la table. Tout passe
  par quatre fonctions `SECURITY DEFINER` appartenant à `coges_ops`, rôle NOLOGIN
  BYPASSRLS créé par `deploy/postgres/init/01-roles.sql` — le patron de `coges_bus`
  (ADR 0032). La table appartient à `coges_owner`, comme `business_events`, et
  `coges_ops` n'y a que les droits nommés : sa portée est cette seule table (T36).
- **Ce que la lecture rend** : des agrégats par tâche (`job_runs_latest`), jamais un
  `company_id`. Le bilan de `/system/workers` ne nomme aucune entreprise.
- **Données personnelles** : `error` ne reçoit que le nom de la classe d'exception et
  le SQLSTATE (200 caractères au plus), jamais le message, qui peut citer une valeur.
- **RLS** : `company_id` est présent (nul pour une tâche de plate-forme), donc FORCE et
  politique tenant standard, comme T37 l'exige de toute table qui le porte.
- **Purge** : `coges_app` n'a pas DELETE et n'en reçoit pas ; `purge_job_runs()` retire
  ce qui a plus de 90 jours.

`outbox_lag()` appartient à `coges_bus`, qui lit déjà `business_events` : il rend le
nombre d'événements en attente et l'âge du plus ancien, toutes entreprises confondues,
sans aucune donnée d'événement.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "job_runs"
APP_ROLE = "coges_app"
ANALYTICS_ROLE = "coges_analytics"
BUS_ROLE = "coges_bus"
OPS_ROLE = "coges_ops"

#: Fonctions de `coges_ops`, et les rôles qui peuvent les appeler.
OPS_FUNCTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("job_run_start(text, uuid)", (APP_ROLE,)),
    ("job_run_finish(bigint, text, text)", (APP_ROLE,)),
    ("job_runs_latest(interval)", (APP_ROLE,)),
    ("purge_job_runs()", (APP_ROLE,)),
)
BUS_FUNCTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (("outbox_lag()", (APP_ROLE,)),)


def upgrade() -> None:
    op.execute("CREATE TYPE job_run_status AS ENUM ('running', 'ok', 'failed')")
    op.execute(
        f"""
        CREATE TABLE {TABLE} (
          id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          job          text NOT NULL CHECK (length(job) BETWEEN 1 AND 100),
          company_id   uuid REFERENCES companies (id),
          started_at   timestamptz NOT NULL DEFAULT now(),
          finished_at  timestamptz,
          status       job_run_status NOT NULL DEFAULT 'running',
          error        varchar(200),
          CONSTRAINT job_runs_finished_coherent
            CHECK ((status = 'running') = (finished_at IS NULL))
        )
        """
    )
    op.execute(f"CREATE INDEX job_runs_job_started_idx ON {TABLE} (job, started_at DESC)")
    op.execute(f"CREATE INDEX job_runs_started_idx ON {TABLE} (started_at)")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE  ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {TABLE}_tenant ON {TABLE}
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )

    # Les `ALTER DEFAULT PRIVILEGES` des révisions 0001 et 0010 ont donné à `coges_app`
    # et à `coges_analytics` des droits sur chaque table neuve : on les reprend tous.
    for role in (APP_ROLE, ANALYTICS_ROLE):
        op.execute(f"REVOKE ALL ON {TABLE} FROM {role}")
        op.execute(f"REVOKE ALL ON SEQUENCE {TABLE}_id_seq FROM {role}")
    # BYPASSRLS franchit les politiques, pas les GRANT (même nécessité qu'en 0010).
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {OPS_ROLE}")
    op.execute(f"GRANT USAGE ON SEQUENCE {TABLE}_id_seq TO {OPS_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {OPS_ROLE}")

    _ops_functions()
    _bus_function()

    # Droits d'exécution **avant** le transfert de propriété : après, les REVOKE de
    # `coges_owner` seraient des no-op silencieux (révision 0010).
    for signature, roles in OPS_FUNCTIONS + BUS_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        for role in roles:
            op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}")

    for owner, functions in ((OPS_ROLE, OPS_FUNCTIONS), (BUS_ROLE, BUS_FUNCTIONS)):
        op.execute(f"GRANT CREATE ON SCHEMA public TO {owner}")
        for signature, _ in functions:
            op.execute(f"ALTER FUNCTION {signature} OWNER TO {owner}")
        op.execute(f"REVOKE CREATE ON SCHEMA public FROM {owner}")


def _ops_functions() -> None:
    # Ouvre une exécution. Validée seule, avant la tâche : un worker tué en cours de
    # route laisse une ligne `running`, que la lecture compte comme un échec.
    op.execute(
        f"""
        CREATE FUNCTION job_run_start(p_job text, p_company_id uuid)
        RETURNS bigint
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           INSERT INTO public.{TABLE} (job, company_id) VALUES (p_job, p_company_id)
           RETURNING id
        $fn$
        """
    )
    # Clôt une exécution, une seule fois.
    op.execute(
        f"""
        CREATE FUNCTION job_run_finish(p_id bigint, p_status text, p_error text)
        RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           UPDATE public.{TABLE}
              SET status = CAST(p_status AS public.job_run_status),
                  finished_at = now(),
                  error = left(p_error, 200)
            WHERE id = p_id
              AND status = 'running'
              AND p_status IN ('ok', 'failed')
        $fn$
        """
    )
    # Bilan par tâche, sur neuf jours : la dernière exécution, la dernière réussite, et
    # pour les tâches par entreprise le nombre d'entreprises dont la **dernière**
    # exécution a réussi ou échoué. Une exécution restée `running` plus de `p_stale` est
    # un échec (worker tué, délai dépassé). Aucun `company_id` ne sort.
    op.execute(
        f"""
        CREATE FUNCTION job_runs_latest(p_stale interval)
        RETURNS TABLE (job text, last_status text, last_started_at timestamptz,
                       last_finished_at timestamptz, last_ok_at timestamptz,
                       companies_ok integer, companies_failed integer)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           WITH runs AS (
              SELECT r.job, r.company_id, r.started_at, r.finished_at,
                     CASE WHEN r.status = 'running' AND r.started_at < now() - p_stale
                          THEN 'failed' ELSE r.status::text END AS status
                FROM public.{TABLE} r
               WHERE r.started_at > now() - interval '9 days'
           ),
           last_run AS (
              SELECT DISTINCT ON (runs.job) runs.job, runs.status, runs.started_at,
                     runs.finished_at
                FROM runs
               ORDER BY runs.job, runs.started_at DESC
           ),
           last_ok AS (
              SELECT runs.job, max(runs.finished_at) AS last_ok_at
                FROM runs WHERE runs.status = 'ok' GROUP BY runs.job
           ),
           per_company AS (
              SELECT DISTINCT ON (runs.job, runs.company_id) runs.job, runs.status
                FROM runs WHERE runs.company_id IS NOT NULL
               ORDER BY runs.job, runs.company_id, runs.started_at DESC
           ),
           counts AS (
              SELECT per_company.job,
                     count(*) FILTER (WHERE per_company.status = 'ok')::integer AS ok,
                     count(*) FILTER (WHERE per_company.status = 'failed')::integer AS failed
                FROM per_company GROUP BY per_company.job
           )
           SELECT l.job, l.status, l.started_at, l.finished_at, o.last_ok_at,
                  coalesce(c.ok, 0), coalesce(c.failed, 0)
             FROM last_run l
             LEFT JOIN last_ok o ON o.job = l.job
             LEFT JOIN counts c ON c.job = l.job
            ORDER BY l.job
        $fn$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION purge_job_runs()
        RETURNS integer
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           WITH purged AS (
              DELETE FROM public.{TABLE}
               WHERE started_at < now() - interval '90 days'
              RETURNING 1)
           SELECT count(*)::integer FROM purged
        $fn$
        """
    )


def _bus_function() -> None:
    # Le retard du relais, toutes entreprises confondues : deux compteurs et une date.
    # Le rebut (`attempts >= 10`) est compté à part : il ne repartira jamais seul, et
    # son âge ne dit rien du relais.
    op.execute(
        """
        CREATE FUNCTION outbox_lag()
        RETURNS TABLE (pending integer, dead_lettered integer, oldest_pending_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           SELECT count(*) FILTER (WHERE e.attempts < 10)::integer,
                  count(*) FILTER (WHERE e.attempts >= 10)::integer,
                  min(e.occurred_at) FILTER (WHERE e.attempts < 10)
             FROM public.business_events e
            WHERE e.published_at IS NULL
        $fn$
        """
    )


def downgrade() -> None:
    for signature, _ in OPS_FUNCTIONS + BUS_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {OPS_ROLE}")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant ON {TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
    op.execute("DROP TYPE IF EXISTS job_run_status")
