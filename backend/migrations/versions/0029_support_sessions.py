"""Accès support encadré, lot admin 4 (ADR 0092).

Une **session de support** donne à un compte de l'équipe CoGes un accès en lecture seule
aux données d'une entreprise, pour une durée bornée, par **le même chemin** qu'un
utilisateur de l'entreprise : `coges_app`, la RLS normale, `SET LOCAL app.company_id`.
Ce lot n'ajoute ni rôle PostgreSQL ni politique qui ouvrirait une table commerciale.

- **`support_sessions`** : le fait qu'un accès a eu lieu — par qui, pourquoi, quand —, et
  rien de commercial. Elle porte `company_id` : RLS FORCE, politique tenant (T37), plus
  une politique qui ne nomme que `coges_app_platform` (qui ouvre et ferme).
- **`coges_app` lit cinq colonnes** (`id`, `company_id`, `started_at`, `expires_at`,
  `ended_at`), pour sa seule entreprise : l'API relit la session à chaque requête d'un
  jeton de support (fermée ⇒ refusé tout de suite), et le bandeau la montre à tous les
  utilisateurs. Ni le compte de l'équipe ni la justification : l'entreprise lit la
  justification dans son propre journal d'activité.
- **Bris de glace** (ADR 0092) : `granted_by_user_id` reste NULL et la justification est
  obligatoire. Le consentement du gérant remplira la colonne le jour venu.
- **Durée** : 4 h au plus, en base aussi. Une seule session ouverte par entreprise.
- **Garde `support_sessions_guard`** (`CG008`) : une session ne change qu'une fois, pour
  être fermée (`ended_at`, `ended_by`). Rien d'autre ne se réécrit.
- `notifications.type` admet `support_access` (le gérant est prévenu).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "coges_app"
ANALYTICS_ROLE = "coges_analytics"
PLATFORM_ROLE = "coges_app_platform"
BACKUP_ROLE = "coges_backup"

#: Durée maximale d'une session, en heures (ADR 0092). Le service applique la même.
MAX_HOURS = 4
#: Ce que l'API commerçante lit, et rien de plus.
TENANT_COLUMNS = "id, company_id, started_at, expires_at, ended_at"

_TYPES_BEFORE = (
    "'stock_low','stock_out','debt_due','sale_cancelled','forecast_alert',"
    "'insight_critical','login_failures','trial_ending'"
)
_TYPES_AFTER = f"{_TYPES_BEFORE},'support_access'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE support_sessions (
          id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id         uuid NOT NULL REFERENCES companies (id) ON DELETE RESTRICT,
          platform_user_id   uuid NOT NULL REFERENCES platform_users (id),
          justification      varchar(1000),
          granted_by_user_id uuid,
          started_at         timestamptz NOT NULL DEFAULT now(),
          expires_at         timestamptz NOT NULL,
          ended_at           timestamptz,
          ended_by           uuid REFERENCES platform_users (id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT support_sessions_granter_fk FOREIGN KEY (company_id, granted_by_user_id)
            REFERENCES users (company_id, id),
          -- Bris de glace : sans accord du gérant, le « pourquoi » est obligatoire.
          CONSTRAINT support_sessions_justified CHECK (
            granted_by_user_id IS NOT NULL
            OR length(btrim(coalesce(justification, ''))) >= 10
          ),
          CONSTRAINT support_sessions_bounded CHECK (
            expires_at > started_at AND expires_at <= started_at + interval '{MAX_HOURS} hours'
          ),
          CONSTRAINT support_sessions_end_after_start CHECK (ended_at IS NULL OR ended_at >= started_at),
          CONSTRAINT support_sessions_closer_coherent CHECK (ended_by IS NULL OR ended_at IS NOT NULL)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX support_sessions_one_open ON support_sessions (company_id) "
        "WHERE ended_at IS NULL"
    )
    op.execute(
        "CREATE INDEX support_sessions_company_idx ON support_sessions (company_id, started_at DESC)"
    )

    op.execute(
        """
        CREATE FUNCTION support_sessions_guard() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $fn$
        BEGIN
          IF OLD.ended_at IS NOT NULL
             OR NEW.ended_at IS NULL
             OR (NEW.id, NEW.company_id, NEW.platform_user_id, NEW.justification,
                 NEW.granted_by_user_id, NEW.started_at, NEW.expires_at, NEW.created_at)
                IS DISTINCT FROM
                (OLD.id, OLD.company_id, OLD.platform_user_id, OLD.justification,
                 OLD.granted_by_user_id, OLD.started_at, OLD.expires_at, OLD.created_at)
          THEN
            RAISE EXCEPTION 'une session de support ne change que pour être fermée, une fois'
              USING ERRCODE = 'CG008';
          END IF;
          RETURN NEW;
        END
        $fn$
        """
    )
    op.execute(
        """
        CREATE TRIGGER support_sessions_guard BEFORE UPDATE ON support_sessions
          FOR EACH ROW EXECUTE FUNCTION support_sessions_guard()
        """
    )

    op.execute("ALTER TABLE support_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE support_sessions FORCE  ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY support_sessions_tenant ON support_sessions
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )
    op.execute(
        f"""
        CREATE POLICY support_sessions_platform ON support_sessions TO {PLATFORM_ROLE}
          USING (true) WITH CHECK (true)
        """
    )

    # Les privilèges par défaut ouvrent toute table neuve à `coges_app` et
    # `coges_analytics` : on les reprend, puis on rend à `coges_app` ses cinq colonnes.
    for role in (APP_ROLE, ANALYTICS_ROLE):
        op.execute(f"REVOKE ALL ON support_sessions FROM {role}")
    op.execute(f"GRANT SELECT ({TENANT_COLUMNS}) ON support_sessions TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON support_sessions TO {PLATFORM_ROLE}")
    op.execute(f"GRANT UPDATE (ended_at, ended_by) ON support_sessions TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT ON support_sessions TO {BACKUP_ROLE}")

    _notification_types(_TYPES_AFTER)


def _notification_types(types: str) -> None:
    op.execute("ALTER TABLE notifications DROP CONSTRAINT notifications_type_check")
    op.execute(
        f"ALTER TABLE notifications ADD CONSTRAINT notifications_type_check "
        f"CHECK (type IN ({types}))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE notifications NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM notifications WHERE type = 'support_access'")
    op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
    _notification_types(_TYPES_BEFORE)

    op.execute("DROP TABLE support_sessions")
    op.execute("DROP FUNCTION support_sessions_guard()")
