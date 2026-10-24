"""Abonnements, lot admin 3 : offres, essai, plafond d'utilisateurs (ADR 0091).

Referme le point P8 (ADR 0043, « aucun palier commercial en V1 »).

- **`plans`** (plateforme, sans `company_id`, donc hors RLS) : trois offres vendables,
  Starter (4 900 FCFA, 3 comptes), Business (9 900, 7), Premium (14 900, 10). `max_users`
  NULL = illimité : le futur palier « sur devis » est une ligne à ajouter
  (`is_orderable = false` d'abord), pas un développement. `features` en jsonb : liste
  indicative, rien n'est encore réservé à une offre dans le produit.
- **`subscriptions`** : l'état courant de l'abonnement d'une entreprise, une ligne par
  entreprise. Elle porte `company_id`, donc RLS FORCE et politique tenant (T37), plus une
  politique qui ne nomme que `coges_app_platform`. `coges_app` n'y a **aucun** droit :
  c'est une donnée plateforme à propos d'une entreprise, pas une donnée de l'entreprise.
- **`subscription_payments`** (sans `company_id`) : paiements déclarés par l'équipe,
  append-only, clé d'idempotence en colonne (la table `idempotency_keys` est par
  entreprise, sous RLS commerçante).
- **`coges_billing`** (NOLOGIN, NOBYPASSRLS, créé hors migration :
  `deploy/sql/create_billing_role.sql`) possède deux fonctions `SECURITY DEFINER`, posées
  en trigger :
  * `companies_start_trial()` : toute entreprise naît avec un essai Premium de 30 jours ;
  * `users_plan_limit()` : un compte qui **devient** actif au-delà du plafond de l'offre
    est refusé (`CG007`, plafond en DETAIL). L'abonnement est verrouillé `FOR UPDATE` :
    deux créations simultanées sur la dernière place ne passent pas toutes les deux.
  Il compte les comptes sous la RLS : l'entreprise du contexte, et elle seule.
- **Existant** : chaque entreprise reçoit un essai Premium de 30 jours à compter de la
  migration, et `companies.status` passe de `active` à `trial` (défaut de la colonne
  aussi). `notifications.type` admet `trial_ending`.

Prérequis : `coges_billing` doit exister avant cette révision.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "coges_app"
ANALYTICS_ROLE = "coges_analytics"
PLATFORM_ROLE = "coges_app_platform"
BILLING_ROLE = "coges_billing"
BACKUP_ROLE = "coges_backup"

TABLES = ("plans", "subscriptions", "subscription_payments")
#: Durée de l'essai : ici, dans la fonction qui le crée avec l'entreprise (ADR 0091).
TRIAL_DAYS = 30
FUNCTIONS = ("companies_start_trial()", "users_plan_limit()")

_TYPES_BEFORE = (
    "'stock_low','stock_out','debt_due','sale_cancelled','forecast_alert',"
    "'insight_critical','login_failures'"
)
_TYPES_AFTER = f"{_TYPES_BEFORE},'trial_ending'"

_REQUIRE_ROLE = f"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{BILLING_ROLE}') THEN
    RAISE EXCEPTION 'rôle {BILLING_ROLE} absent : lancer deploy/sql/create_billing_role.sql '
                    'sur ce cluster avant la révision 0028';
  END IF;
END
$$
"""


def upgrade() -> None:
    op.execute(_REQUIRE_ROLE)
    op.execute("CREATE TYPE subscription_status AS ENUM ('trial', 'active', 'past_due', 'suspended')")
    op.execute(
        """
        CREATE TABLE plans (
          id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          code         text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z_]{1,30}$'),
          name         text NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
          price_fcfa   numeric(14,2) CHECK (price_fcfa >= 0),
          max_users    integer CHECK (max_users > 0),
          features     jsonb NOT NULL DEFAULT '[]'::jsonb
                       CHECK (jsonb_typeof(features) = 'array'),
          is_orderable boolean NOT NULL DEFAULT true,
          created_at   timestamptz NOT NULL DEFAULT now(),
          -- Une offre vendable a un prix ; « sur devis » (NULL) ne se vend pas en libre.
          CONSTRAINT plans_orderable_has_price CHECK (NOT is_orderable OR price_fcfa IS NOT NULL)
        )
        """
    )
    op.execute(
        """
        INSERT INTO plans (code, name, price_fcfa, max_users, features) VALUES
          ('starter',  'Starter',   4900, 3,
           '["sales","inventory","money","contacts"]'),
          ('business', 'Business',  9900, 7,
           '["sales","inventory","money","contacts","intelligence","imports_exports"]'),
          ('premium',  'Premium',  14900, 10,
           '["sales","inventory","money","contacts","intelligence","imports_exports","premium"]')
        """
    )
    op.execute(
        """
        CREATE TABLE subscriptions (
          id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id         uuid NOT NULL UNIQUE REFERENCES companies (id) ON DELETE RESTRICT,
          plan_id            uuid NOT NULL REFERENCES plans (id) ON DELETE RESTRICT,
          status             subscription_status NOT NULL DEFAULT 'trial',
          trial_ends_at      timestamptz,
          started_at         timestamptz NOT NULL DEFAULT now(),
          current_period_end timestamptz,
          -- Dernier avertissement de fin d'essai envoyé (7, 3 puis 1 jour) : la tâche de
          -- nuit ne prévient jamais deux fois pour le même palier.
          trial_warned_days  smallint CHECK (trial_warned_days IN (7, 3, 1)),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT subscriptions_trial_has_end CHECK (status <> 'trial' OR trial_ends_at IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX subscriptions_trial_ends_idx ON subscriptions (trial_ends_at) WHERE status = 'trial'")
    op.execute(
        """
        CREATE TABLE subscription_payments (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          subscription_id uuid NOT NULL REFERENCES subscriptions (id) ON DELETE RESTRICT,
          amount_fcfa     numeric(14,2) NOT NULL CHECK (amount_fcfa > 0),
          paid_at         timestamptz NOT NULL,
          method          pay_method NOT NULL
                          -- En texte : `wave` et `orange_money` (révision 0015) ne
                          -- s'emploient pas comme constantes d'énumération dans la
                          -- transaction qui les a créées (migration de bout en bout).
                          CHECK (method::text IN ('wave', 'orange_money', 'cash', 'bank_transfer')),
          note            varchar(500),
          recorded_by     uuid NOT NULL REFERENCES platform_users (id),
          idempotency_key varchar(200) NOT NULL UNIQUE,
          created_at      timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT subscription_payments_not_future CHECK (paid_at <= created_at + interval '5 minutes')
        )
        """
    )
    op.execute(
        "CREATE INDEX subscription_payments_subscription_idx "
        "ON subscription_payments (subscription_id, paid_at DESC)"
    )

    # L'existant : un essai Premium de 30 jours, posé **avant** la RLS (le propriétaire
    # y serait soumis, FORCE oblige).
    op.execute(
        f"""
        INSERT INTO subscriptions (company_id, plan_id, status, trial_ends_at)
        SELECT c.id, p.id, 'trial', now() + interval '{TRIAL_DAYS} days'
          FROM companies c CROSS JOIN plans p
         WHERE p.code = 'premium'
        """
    )
    # `companies` est en FORCE : levé le temps de recaler le statut des entreprises
    # existantes (la garde CG006 laisse passer `coges_owner`).
    op.execute("ALTER TABLE companies NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE companies SET status = 'trial' WHERE status = 'active'
        """
    )
    op.execute("ALTER TABLE companies FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE companies ALTER COLUMN status SET DEFAULT 'trial'")

    op.execute("ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE subscriptions FORCE  ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY subscriptions_tenant ON subscriptions
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )
    op.execute(
        f"""
        CREATE POLICY subscriptions_platform ON subscriptions TO {PLATFORM_ROLE}
          USING (true) WITH CHECK (true)
        """
    )

    # Les privilèges par défaut des révisions 0001 et 0010 ouvrent toute table neuve à
    # `coges_app` et `coges_analytics` : on les reprend tous.
    for table in TABLES:
        for role in (APP_ROLE, ANALYTICS_ROLE):
            op.execute(f"REVOKE ALL ON {table} FROM {role}")
        op.execute(f"GRANT SELECT ON {table} TO {BACKUP_ROLE}")
    op.execute(f"GRANT SELECT ON plans TO {PLATFORM_ROLE}, {BILLING_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON subscriptions TO {PLATFORM_ROLE}, {BILLING_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON subscription_payments TO {PLATFORM_ROLE}")
    # Compter les comptes actifs de l'entreprise du contexte : quatre colonnes, rien d'autre.
    op.execute(f"GRANT SELECT (id, company_id, is_active, deleted_at) ON users TO {BILLING_ROLE}")

    _billing_functions()
    # Les triggers d'abord : les poser exige EXECUTE, que `coges_owner` perd au transfert.
    op.execute(
        """
        CREATE TRIGGER companies_start_trial AFTER INSERT ON companies
          FOR EACH ROW EXECUTE FUNCTION companies_start_trial()
        """
    )
    op.execute(
        """
        CREATE TRIGGER users_plan_limit BEFORE INSERT OR UPDATE OF is_active, deleted_at ON users
          FOR EACH ROW EXECUTE FUNCTION users_plan_limit()
        """
    )

    for signature in FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT CREATE ON SCHEMA public TO {BILLING_ROLE}")
    for signature in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {BILLING_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {BILLING_ROLE}")
    _notification_types(_TYPES_AFTER)


def _billing_functions() -> None:
    op.execute(
        f"""
        CREATE FUNCTION companies_start_trial() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
        BEGIN
          INSERT INTO public.subscriptions (company_id, plan_id, status, trial_ends_at)
          SELECT NEW.id, p.id, 'trial', now() + interval '{TRIAL_DAYS} days'
            FROM public.plans p WHERE p.code = 'premium';
          RETURN NULL;
        END
        $fn$
        """
    )
    # Seul le passage à l'état actif compte : création, réactivation, restauration. Une
    # modification d'un compte déjà actif ne revérifie rien (un plafond baissé après coup
    # ne coupe personne : la descente d'offre est refusée en amont, ADR 0091).
    op.execute(
        """
        CREATE FUNCTION users_plan_limit() RETURNS trigger
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
          SELECT p.max_users INTO v_max
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


def _notification_types(types: str) -> None:
    op.execute("ALTER TABLE notifications DROP CONSTRAINT notifications_type_check")
    op.execute(
        f"ALTER TABLE notifications ADD CONSTRAINT notifications_type_check "
        f"CHECK (type IN ({types}))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE notifications NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM notifications WHERE type = 'trial_ending'")
    op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
    _notification_types(_TYPES_BEFORE)

    op.execute("DROP TRIGGER users_plan_limit ON users")
    op.execute("DROP TRIGGER companies_start_trial ON companies")
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    op.execute(f"REVOKE SELECT (id, company_id, is_active, deleted_at) ON users FROM {BILLING_ROLE}")

    op.execute("ALTER TABLE companies ALTER COLUMN status SET DEFAULT 'active'")
    op.execute("ALTER TABLE companies NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE companies SET status = 'active' WHERE status = 'trial'
        """
    )
    op.execute("ALTER TABLE companies FORCE ROW LEVEL SECURITY")

    op.execute("DROP TABLE subscription_payments")
    op.execute("DROP TABLE subscriptions")
    op.execute("DROP TABLE plans")
    op.execute("DROP TYPE subscription_status")
