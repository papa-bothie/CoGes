-- Rôle de l'inscription libre-service (lot 30, ADR 0118). À lancer UNE fois par cluster
-- (Neon préprod, PUIS prod), en `neondb_owner`, AVANT la migration 0039 :
--
--   psql "$NEONDB_OWNER_DSN" -f deploy/sql/create_signup_role.sql
--
-- NOLOGIN, NOBYPASSRLS : personne ne s'y connecte. Il possède les fonctions
-- SECURITY DEFINER qui lisent et écrivent `signup_requests` et `signup_email_tokens`,
-- appelées sous `coges_app` (qui n'a AUCUN droit direct sur ces deux tables). Ses droits
-- sont posés par la migration 0039.
--
-- `coges_owner` en devient membre sans héritage : la migration lui transfère la propriété
-- des fonctions, rien de plus.
--
-- pg_dump ne sauvegarde pas les rôles : une restauration sur un projet neuf exige ce
-- script d'abord (docs/runbooks/sauvegarde.md).

\set ON_ERROR_STOP on

CREATE ROLE coges_signup NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT coges_signup TO coges_owner WITH INHERIT FALSE;
GRANT USAGE ON SCHEMA public TO coges_signup;
