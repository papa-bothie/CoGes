-- Rôle des abonnements (lot admin 3, ADR 0091). À lancer UNE fois par cluster (Neon
-- préprod, puis prod), en `neondb_owner`, AVANT la migration 0028 :
--
--   psql "$NEONDB_OWNER_DSN" -f deploy/sql/create_billing_role.sql
--
-- NOLOGIN, NOBYPASSRLS : personne ne s'y connecte ; il possède deux fonctions
-- SECURITY DEFINER, appelées par trigger sous `coges_app` :
--   * companies_start_trial() : l'essai Premium naît avec l'entreprise ;
--   * users_plan_limit()      : un compte au-delà du plafond de l'offre est refusé.
-- Il lit les comptes sous la RLS (l'entreprise du contexte seulement) ; ses droits sont
-- posés par la migration 0028 (`plans`, `subscriptions`, quatre colonnes de `users`).
--
-- `coges_owner` en devient membre sans héritage : la migration lui transfère la propriété
-- des fonctions, rien de plus.

\set ON_ERROR_STOP on

CREATE ROLE coges_billing NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT coges_billing TO coges_owner WITH INHERIT FALSE;
GRANT USAGE ON SCHEMA public TO coges_billing;
