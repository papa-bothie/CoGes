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

CREATE DATABASE coges      OWNER coges_owner;
CREATE DATABASE coges_test OWNER coges_owner;

\connect coges
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;

\connect coges_test
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;
