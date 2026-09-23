-- Amorçage des rôles et des bases de développement (exécuté une seule fois, à la
-- création du volume PostgreSQL, par le superutilisateur du conteneur).
--
-- Phase 00 : on crée seulement les rôles et les bases. Les GRANT/REVOKE, la RLS et
-- l'interdiction de DELETE sur coges_app sont posés par la migration 0001 en phase 01
-- (§ 7 du Modèle de données).

\set owner_password `echo "$COGES_OWNER_PASSWORD"`
\set app_password   `echo "$COGES_APP_PASSWORD"`

-- Propriétaire du schéma et des migrations : ni superutilisateur, ni BYPASSRLS.
CREATE ROLE coges_owner LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE
    PASSWORD :'owner_password';

-- Rôle applicatif : aucun privilège de contournement (décision 06).
CREATE ROLE coges_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    PASSWORD :'app_password';

-- Propriétaire de la seule fonction d'authentification. NOLOGIN : personne ne peut
-- s'y connecter. BYPASSRLS : indispensable car `companies` et `users` sont en
-- FORCE ROW LEVEL SECURITY, qui s'applique aussi au propriétaire des tables — une
-- fonction SECURITY DEFINER appartenant à coges_owner ne verrait rien (ADR 0005).
CREATE ROLE coges_auth NOLOGIN NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE;

-- coges_owner doit pouvoir transférer la propriété de auth_lookup à coges_auth.
-- WITH INHERIT FALSE : aucune élévation implicite, il faut un SET ROLE explicite.
GRANT coges_auth TO coges_owner WITH INHERIT FALSE;

CREATE DATABASE coges      OWNER coges_owner;
CREATE DATABASE coges_test OWNER coges_owner;

\connect coges
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;
GRANT USAGE ON SCHEMA public TO coges_auth;

\connect coges_test
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;
GRANT USAGE ON SCHEMA public TO coges_auth;
