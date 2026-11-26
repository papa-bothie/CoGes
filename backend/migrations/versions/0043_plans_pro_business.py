"""Offres Pro et Business, droits par offre, droits acquis (prompt 41, ADR 0132).

Amende la révision 0028 (ADR 0091). Ajout seul : le code déjà en production ignore les
colonnes nouvelles et la fonction `current_plan()` (ADR 0083).

- **`plans`** : les codes ne changent pas (`starter`, `business`, `premium` : la licence
  sur site les emploie), seuls les noms affichés. `starter` devient « Pro ». Premium passe
  « sur devis » : prix `NULL`, 10 comptes, `is_orderable = false`. Nouvelle colonne
  `annual_price_fcfa` (`NULL` = pas de paiement annuel), écrite ici, jamais recalculée :
  12 × prix × 0,9. `features` devient la **source des droits** (catalogue fermé,
  `app/core/plan_features.py`).
- **`subscriptions`** : `extra_features` (droits acquis, tableau), `max_users_override`
  (plafond acquis), `is_license` (licence sur site, ADR 0125).
- **`subscription_payments.period_months`** : 1 ou 12.
- **Boutiques existantes** (toutes, licences comprises) : sur `starter`, avec l'import en
  droit acquis et, au-delà de 3 comptes actifs, leur nombre en plafond acquis ; statut et
  dates inchangés. Les licences se reconnaissent au journal de la plateforme.
- **Fonctions de `coges_billing`** : l'essai naît sur `starter` ; le plafond devient
  `COALESCE(max_users_override, plans.max_users)` ; `current_plan()` rend l'offre de
  l'entreprise du contexte, et d'elle seule, à `coges_app` (qui ne lit toujours aucune
  table de la plateforme).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "coges_app"
BILLING_ROLE = "coges_billing"
TRIAL_DAYS = 30
CURRENT_PLAN = "current_plan()"
#: Raison écrite au journal de la plateforme par `activate-license` (ADR 0125).
LICENSE_REASON = "licence sur site"
#: Tables en RLS FORCE lues ou écrites par la recopie de l'existant.
FORCED = ("subscriptions", "users", "companies")

#: Catalogue fermé des droits (copie figée de `app/core/plan_features.py`, testée).
COMMON = (
    "sales",
    "purchases",
    "inventory",
    "dashboard",
    "reports_exports",
    "product_photos",
    "documents",
    "stock_alerts",
)
BUSINESS_ONLY = (
    "imports",
    "physical_inventory",
    "invoice_branding",
    "stock_locations",
    "priority_support",
)


def _json(codes: Sequence[str]) -> str:
    return "[" + ",".join(f'"{code}"' for code in codes) + "]"


_PRO = _json(COMMON)
_BUSINESS = _json(COMMON + BUSINESS_ONLY)

_OLD_FEATURES = {
    "starter": '["sales","inventory","money","contacts"]',
    "business": '["sales","inventory","money","contacts","intelligence","imports_exports"]',
    "premium": '["sales","inventory","money","contacts","intelligence","imports_exports","premium"]',
}


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE plans
          ADD COLUMN annual_price_fcfa numeric(14,2) CHECK (annual_price_fcfa >= 0),
          ADD CONSTRAINT plans_annual_needs_monthly
            CHECK (annual_price_fcfa IS NULL OR price_fcfa IS NOT NULL)
        """
    )
    op.execute(
        f"""
        UPDATE plans SET name = 'Pro', price_fcfa = 4900, annual_price_fcfa = 52920,
                         max_users = 3, features = '{_PRO}', is_orderable = true
         WHERE code = 'starter'
        """
    )
    op.execute(
        f"""
        UPDATE plans SET name = 'Business', price_fcfa = 9900, annual_price_fcfa = 106920,
                         max_users = 7, features = '{_BUSINESS}', is_orderable = true
         WHERE code = 'business'
        """
    )
    op.execute(
        f"""
        UPDATE plans SET name = 'Premium', price_fcfa = NULL, annual_price_fcfa = NULL,
                         max_users = 10, features = '{_BUSINESS}', is_orderable = false
         WHERE code = 'premium'
        """
    )

    op.execute(
        """
        ALTER TABLE subscriptions
          ADD COLUMN extra_features jsonb NOT NULL DEFAULT '[]'::jsonb
            CHECK (jsonb_typeof(extra_features) = 'array'),
          ADD COLUMN max_users_override smallint CHECK (max_users_override > 0),
          ADD COLUMN is_license boolean NOT NULL DEFAULT false
        """
    )
    op.execute(
        """
        ALTER TABLE subscription_payments
          ADD COLUMN period_months smallint NOT NULL DEFAULT 1
            CHECK (period_months IN (1, 12))
        """
    )

    # L'existant : `subscriptions`, `users` et `companies` sont en FORCE, propriétaire
    # compris. Levé le temps de recaler toutes les entreprises (aucun trigger ne porte sur
    # `subscriptions`).
    for table in FORCED:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        UPDATE subscriptions s
           SET plan_id = (SELECT id FROM plans WHERE code = 'starter'),
               extra_features = '["imports"]'::jsonb,
               max_users_override = CASE WHEN a.active > 3 THEN a.active END,
               is_license = EXISTS (
                 SELECT 1 FROM platform_audit_logs l
                  WHERE l.target_company_id = s.company_id
                    AND l.entity_table = 'subscriptions'
                    AND l.diff ->> 'reason' = '{LICENSE_REASON}'
               ) AND s.status = 'active' AND s.current_period_end IS NULL
          FROM (
            SELECT c.id AS company_id,
                   (SELECT count(*) FROM users u
                     WHERE u.company_id = c.id AND u.is_active AND u.deleted_at IS NULL
                   )::smallint AS active
              FROM companies c
          ) a
         WHERE a.company_id = s.company_id
        """
    )
    for table in FORCED:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Les fonctions existantes appartiennent à `coges_billing`, dont `coges_owner` est
    # membre sans hériter : on les remplace en son nom (comme la révision 0027).
    op.execute(f"GRANT CREATE ON SCHEMA public TO {BILLING_ROLE}")
    op.execute(f"SET LOCAL ROLE {BILLING_ROLE}")
    _start_trial("starter")
    _plan_limit(with_override=True)
    _current_plan()
    op.execute(f"REVOKE ALL ON FUNCTION {CURRENT_PLAN} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {CURRENT_PLAN} TO {APP_ROLE}")
    op.execute("RESET ROLE")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {BILLING_ROLE}")


def _start_trial(plan_code: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION companies_start_trial() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
        BEGIN
          INSERT INTO public.subscriptions (company_id, plan_id, status, trial_ends_at)
          SELECT NEW.id, p.id, 'trial', now() + interval '{TRIAL_DAYS} days'
            FROM public.plans p WHERE p.code = '{plan_code}';
          RETURN NULL;
        END
        $fn$
        """
    )


def _plan_limit(*, with_override: bool) -> None:
    cap = "COALESCE(s.max_users_override::integer, p.max_users)" if with_override else "p.max_users"
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION users_plan_limit() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
        DECLARE
          v_max integer;
          v_active integer;
        BEGIN
          IF NOT (NEW.is_active AND NEW.deleted_at IS NULL) THEN
            RETURN NEW;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.is_active AND OLD.deleted_at IS NULL THEN
            RETURN NEW;
          END IF;
          SELECT {cap} INTO v_max
            FROM public.subscriptions s JOIN public.plans p ON p.id = s.plan_id
           WHERE s.company_id = NEW.company_id
             FOR UPDATE OF s;
          IF NOT FOUND OR v_max IS NULL THEN
            RETURN NEW;
          END IF;
          SELECT count(*) INTO v_active
            FROM public.users u
           WHERE u.company_id = NEW.company_id AND u.is_active AND u.deleted_at IS NULL
             AND u.id <> NEW.id;
          IF v_active >= v_max THEN
            RAISE EXCEPTION 'plafond d''utilisateurs de l''offre atteint'
              USING ERRCODE = 'CG007', DETAIL = v_max::text;
          END IF;
          RETURN NEW;
        END
        $fn$
        """
    )


def _current_plan() -> None:
    # Deux barrières : le filtre sur `app.company_id` et la RLS de `subscriptions` et de
    # `users` (le rôle n'a pas BYPASSRLS). Sans contexte, aucune ligne.
    op.execute(
        """
        CREATE FUNCTION current_plan()
        RETURNS TABLE (
          plan_code          text,
          plan_name          text,
          status             text,
          trial_ends_at      timestamptz,
          current_period_end timestamptz,
          is_license         boolean,
          max_users          integer,
          active_users       integer,
          features           jsonb,
          extra_features     jsonb
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
          SELECT p.code, p.name, s.status::text, s.trial_ends_at, s.current_period_end,
                 s.is_license,
                 COALESCE(s.max_users_override::integer, p.max_users),
                 (SELECT count(*)::integer FROM public.users u
                   WHERE u.company_id = s.company_id AND u.is_active AND u.deleted_at IS NULL),
                 (SELECT COALESCE(jsonb_agg(DISTINCT f.code ORDER BY f.code), '[]'::jsonb)
                    FROM jsonb_array_elements_text(p.features || s.extra_features) AS f(code)),
                 s.extra_features
            FROM public.subscriptions s JOIN public.plans p ON p.id = s.plan_id
           WHERE s.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid
        $fn$
        """
    )


def downgrade() -> None:
    op.execute(f"GRANT CREATE ON SCHEMA public TO {BILLING_ROLE}")
    op.execute(f"SET LOCAL ROLE {BILLING_ROLE}")
    op.execute(f"DROP FUNCTION {CURRENT_PLAN}")
    _plan_limit(with_override=False)
    _start_trial("premium")
    op.execute("RESET ROLE")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {BILLING_ROLE}")

    op.execute("ALTER TABLE subscription_payments DROP COLUMN period_months")
    op.execute(
        """
        ALTER TABLE subscriptions
          DROP COLUMN is_license,
          DROP COLUMN max_users_override,
          DROP COLUMN extra_features
        """
    )
    op.execute("ALTER TABLE plans DROP CONSTRAINT plans_annual_needs_monthly")
    op.execute("ALTER TABLE plans DROP COLUMN annual_price_fcfa")
    for code, name, price, max_users in (
        ("starter", "Starter", 4900, 3),
        ("business", "Business", 9900, 7),
        ("premium", "Premium", 14900, 10),
    ):
        op.execute(
            f"""
            UPDATE plans SET name = '{name}', price_fcfa = {price}, max_users = {max_users},
                             features = '{_OLD_FEATURES[code]}', is_orderable = true
             WHERE code = '{code}'
            """
        )
