-- Amorçage des rôles et de la base d'une installation sur site (ADR 0124). Exécuté une
-- seule fois, à la création du volume PostgreSQL, par le superutilisateur du conteneur.
--
-- Les MÊMES rôles, attributs et GRANT que deploy/postgres/init/01-roles.sql (un test
-- compare les deux fichiers : si l'un change sans l'autre, la CI échoue), mais :
--   • la seule base `coges` (ni coges_test ni coges_e2e) ;
--   • aucun mot de passe par défaut : chacun vient de coges.env, et le compose refuse de
--     démarrer s'il manque.
-- Les GRANT de tables, la RLS et l'interdiction de DELETE sont posés par les migrations.

\set ON_ERROR_STOP on
\set owner_password     `echo "$COGES_OWNER_PASSWORD"`
\set app_password       `echo "$COGES_APP_PASSWORD"`
\set relay_password     `echo "$COGES_RELAY_PASSWORD"`
\set analytics_password `echo "$COGES_ANALYTICS_PASSWORD"`
\set platform_password  `echo "$COGES_PLATFORM_PASSWORD"`

-- Propriétaire du schéma et des migrations : ni superutilisateur, ni BYPASSRLS.
CREATE ROLE coges_owner LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE
    PASSWORD :'owner_password';

-- Rôle applicatif : aucun privilège de contournement (décision 06).
CREATE ROLE coges_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    PASSWORD :'app_password';

-- Propriétaire de la seule fonction d'authentification (ADR 0005). NOLOGIN.
CREATE ROLE coges_auth NOLOGIN NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE;

-- Relais de l'outbox : EXECUTE sur des fonctions SECURITY DEFINER, rien d'autre (ADR 0032).
CREATE ROLE coges_relay LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    PASSWORD :'relay_password';

-- Rôle analytique : seul autorisé à DELETE, sur les projections reconstruisibles.
CREATE ROLE coges_analytics LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    PASSWORD :'analytics_password';

-- Propriétaire des fonctions du bus (ADR 0032). NOLOGIN.
CREATE ROLE coges_bus NOLOGIN NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE;

-- Propriétaire des fonctions de surveillance (ADR 0077). NOLOGIN.
CREATE ROLE coges_ops NOLOGIN NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE;

-- Sauvegarde (ADR 0084) : la révision 0023 lui donne ses droits, le rôle doit donc
-- exister. Mot de passe VIDE : personne ne peut s'y connecter. La sauvegarde locale est
-- le sujet du lot 4, qui décidera de son usage.
CREATE ROLE coges_backup LOGIN BYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    NOREPLICATION CONNECTION LIMIT 2 PASSWORD '';
ALTER ROLE coges_backup SET default_transaction_read_only = on;

-- Administration de la plateforme (ADR 0089) : métadonnées seulement. Lu sur le poste par
-- la tâche de nuit des abonnements (ADR 0091).
CREATE ROLE coges_app_platform LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    PASSWORD :'platform_password';

-- Abonnements (ADR 0091). NOLOGIN, NOBYPASSRLS.
CREATE ROLE coges_billing NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

-- Inscription libre-service (ADR 0118) : éteinte sur site, mais ses fonctions existent.
CREATE ROLE coges_signup NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

-- coges_owner transfère la propriété des fonctions à leur rôle final, par SET ROLE explicite.
GRANT coges_auth TO coges_owner WITH INHERIT FALSE;
GRANT coges_bus  TO coges_owner WITH INHERIT FALSE;
GRANT coges_ops  TO coges_owner WITH INHERIT FALSE;
GRANT coges_billing TO coges_owner WITH INHERIT FALSE;
GRANT coges_signup TO coges_owner WITH INHERIT FALSE;

CREATE DATABASE coges OWNER coges_owner;

\connect coges
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;
GRANT USAGE ON SCHEMA public TO coges_auth;
GRANT USAGE ON SCHEMA public TO coges_relay;
GRANT USAGE ON SCHEMA public TO coges_analytics;
GRANT USAGE ON SCHEMA public TO coges_bus;
GRANT USAGE ON SCHEMA public TO coges_app_platform;
GRANT USAGE ON SCHEMA public TO coges_billing;
GRANT USAGE ON SCHEMA public TO coges_signup;
