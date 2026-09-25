"""CoGes Intelligence : features figées, prévisions et insights.

Reprend le § 8.9 du Modèle de données (`ml_feature_snapshots`, `forecasts`,
`insights`), ses index du § 8.10 et sa RLS du § 8.11, avec trois écarts assumés
(ADR 0036, 0037) :

* **`insufficient_history`** rejoint l'ENUM `insight_type`. « Données insuffisantes »
  doit être un fait persisté : l'API ne calcule rien, elle ne peut donc pas déduire
  elle-même qu'un produit est sous le seuil d'historique.
* **Privilèges resserrés.** L'Architecture dit de `ml_feature_snapshots` qu'elle n'est
  « jamais lue par l'application », de `forecasts` qu'elle n'est « jamais écrite par un
  endpoint applicatif », et d'`insights.status` qu'il est « la seule colonne modifiable
  par l'application ». Ces trois phrases deviennent des `GRANT`, au lieu de rester des
  promesses du code : T35 devient structurel.
* **Aucun `DELETE`**, pas même pour `coges_analytics`. Les features sont écrites une
  fois et jamais réécrites (§ 6.2) ; un insight périmé sort de l'affichage par
  `valid_until`, filtré à la lecture.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "coges_app"
ANALYTICS_ROLE = "coges_analytics"

#: Tables tenant-scoped créées par cette révision.
TENANT_TABLES = ("ml_feature_snapshots", "forecasts", "insights")

#: Valeurs de l'ENUM telles que la révision 0001 les a créées : le downgrade recrée
#: le type à l'identique.
ORIGINAL_INSIGHT_TYPES = (
    "stockout_risk",
    "slow_mover",
    "demand_spike",
    "margin_drop",
    "expense_anomaly",
    "cash_shortfall",
    "debt_overdue",
    "cashier_anomaly",
)


def _rls(table: str) -> None:
    """Politique tenant du projet : forme `NULLIF`, ADR 0003."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE  ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant ON {table}
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )


# --------------------------------------------------------------------- tables


def _ml_feature_snapshots() -> None:
    """Features et labels figés par `as_of` (§ 6.2, anti-fuite temporelle)."""
    op.execute(
        """
        CREATE TABLE ml_feature_snapshots (
           id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
           company_id uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           product_id uuid NOT NULL,
           as_of      date NOT NULL,
           features   jsonb NOT NULL,
           labels     jsonb,
           created_at timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT mlf_uq UNIQUE (company_id, product_id, as_of),
           CONSTRAINT mlf_product_fk FOREIGN KEY (company_id, product_id)
             REFERENCES products (company_id, id) ON DELETE RESTRICT
        )
        """
    )


def _forecasts() -> None:
    """Prévisions persistées : le pipeline écrit, l'API lit (§ 4.11)."""
    op.execute(
        """
        CREATE TABLE forecasts (
           id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           product_id    uuid,
           forecast_type forecast_type NOT NULL,
           as_of         date NOT NULL,
           horizon_date  date NOT NULL,
           yhat          numeric(14,4) NOT NULL,
           yhat_lower    numeric(14,4),
           yhat_upper    numeric(14,4),
           model_name    text NOT NULL,
           model_version text NOT NULL,
           metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
           generated_at  timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT forecasts_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT forecasts_product_fk FOREIGN KEY (company_id, product_id)
             REFERENCES products (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT forecasts_horizon CHECK (horizon_date >= as_of),
           CONSTRAINT forecasts_interval CHECK (
             yhat_lower IS NULL OR yhat_upper IS NULL OR yhat_lower <= yhat_upper),
           -- PostgreSQL 15+ : product_id nullable doit participer à l'unicité
           CONSTRAINT forecasts_idem UNIQUE NULLS NOT DISTINCT
             (company_id, forecast_type, product_id, as_of, horizon_date, model_version)
        )
        """
    )
    op.execute(
        "CREATE INDEX forecasts_read ON forecasts "
        "(company_id, product_id, forecast_type, horizon_date)"
    )
    op.execute("CREATE INDEX forecasts_asof ON forecasts (company_id, as_of DESC)")


def _insights() -> None:
    """Anomalies, observations et recommandations persistées (§ 4.12)."""
    op.execute(
        """
        CREATE TABLE insights (
           id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           insight_type  insight_type NOT NULL,
           severity      insight_severity NOT NULL DEFAULT 'info',
           title         text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 160),
           body          text,
           entity_table  text CHECK (entity_table IN ('products','customers','suppliers',
                           'expense_categories','sales','users')),
           entity_id     uuid,
           evidence      jsonb NOT NULL DEFAULT '{}'::jsonb,
           dedupe_key    text NOT NULL,
           model_name    text,
           model_version text,
           status        insight_status NOT NULL DEFAULT 'new',
           read_at       timestamptz,
           resolved_at   timestamptz,
           generated_at  timestamptz NOT NULL DEFAULT now(),
           valid_until   timestamptz,
           CONSTRAINT insights_tenant_uq UNIQUE (company_id, id),
           -- référence souple assumée : pas de FK polymorphe, l'insight survit à
           -- l'archivage de sa cible ; les deux colonnes vont par paire
           CONSTRAINT insights_entity_pair CHECK (num_nonnulls(entity_table, entity_id) <> 1),
           CONSTRAINT insights_read_coherent CHECK (status <> 'new' OR read_at IS NULL),
           CONSTRAINT insights_resolved_coherent CHECK (
             (status = 'resolved') = (resolved_at IS NOT NULL))
        )
        """
    )
    # Idempotence : un rejeu met à jour l'insight vivant ; un insight écarté ne bloque
    # pas une réémission si le problème réapparaît (T34).
    op.execute(
        "CREATE UNIQUE INDEX insights_dedupe_uq ON insights (company_id, dedupe_key) "
        "WHERE status <> 'dismissed'"
    )
    op.execute(
        "CREATE INDEX insights_feed ON insights "
        "(company_id, status, severity, generated_at DESC)"
    )
    op.execute("CREATE INDEX insights_entity ON insights (company_id, entity_table, entity_id)")


# ----------------------------------------------------------------- privilèges


def _privileges() -> None:
    """Les règles d'accès de l'Architecture, écrites en `GRANT` (ADR 0036).

    Les `ALTER DEFAULT PRIVILEGES` de la révision 0001 ont donné à `coges_app`
    `SELECT, INSERT, UPDATE` sur chaque table neuve : on les reprend ici.
    """
    # « Jamais lue par l'application » (§ 6) : aucun privilège, pas même SELECT.
    op.execute(f"REVOKE ALL ON ml_feature_snapshots FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON SEQUENCE ml_feature_snapshots_id_seq FROM {APP_ROLE}")
    # « Écrite exclusivement par le processus analytique » (§ 4.11).
    op.execute(f"REVOKE INSERT, UPDATE ON forecasts FROM {APP_ROLE}")
    # « status : seule colonne modifiable par l'application » (§ 4.12) ; ses deux
    # horodatages l'accompagnent, sans quoi les CHECK croisés seraient intenables.
    op.execute(f"REVOKE INSERT, UPDATE ON insights FROM {APP_ROLE}")
    op.execute(f"GRANT UPDATE (status, read_at, resolved_at) ON insights TO {APP_ROLE}")

    # Le pipeline : features écrites une fois (seuls les labels, connus plus tard,
    # se complètent), résultats en ON CONFLICT DO UPDATE, alerte d'un insight critique.
    op.execute(f"GRANT INSERT ON ml_feature_snapshots TO {ANALYTICS_ROLE}")
    op.execute(f"GRANT UPDATE (labels) ON ml_feature_snapshots TO {ANALYTICS_ROLE}")
    op.execute(f"GRANT USAGE ON SEQUENCE ml_feature_snapshots_id_seq TO {ANALYTICS_ROLE}")
    op.execute(f"GRANT INSERT, UPDATE ON forecasts, insights TO {ANALYTICS_ROLE}")
    op.execute(f"GRANT INSERT ON notifications TO {ANALYTICS_ROLE}")


def _drop_privileges() -> None:
    op.execute(f"REVOKE INSERT ON notifications FROM {ANALYTICS_ROLE}")
    for table in TENANT_TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM {ANALYTICS_ROLE}")
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")


# --------------------------------------------------------------------- upgrade


def upgrade() -> None:
    # Ajoutée mais jamais utilisée dans cette transaction : PostgreSQL l'autorise.
    op.execute("ALTER TYPE insight_type ADD VALUE IF NOT EXISTS 'insufficient_history'")

    _ml_feature_snapshots()
    _forecasts()
    _insights()
    for table in TENANT_TABLES:
        _rls(table)
    _privileges()


def downgrade() -> None:
    _drop_privileges()
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table}")

    # Une valeur d'ENUM ne se retire pas : le type est recréé tel que 0001 l'a posé.
    # Plus aucune table ne l'utilise une fois `insights` supprimée.
    values = ", ".join(f"'{value}'" for value in ORIGINAL_INSIGHT_TYPES)
    op.execute("DROP TYPE insight_type")
    op.execute(f"CREATE TYPE insight_type AS ENUM ({values})")
