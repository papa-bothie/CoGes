-- Amorçage des rôles et des bases de développement (exécuté une seule fois, à la
-- création du volume PostgreSQL, par le superutilisateur du conteneur).
--
-- Phase 00 : on crée seulement les rôles et les bases. Les GRANT/REVOKE, la RLS et
-- l'interdiction de DELETE sur coges_app sont posés par la migration 0001 en phase 01
-- (§ 7 du Modèle de données).
--
-- Phase 08 : trois rôles s'ajoutent pour le chemin asynchrone (ADR 0032). Un rôle
-- est un objet de **cluster**, pas de base : il ne peut pas naître d'une migration.
-- Après modification de ce fichier : `docker compose down -v && make up`.

\set owner_password     `echo "$COGES_OWNER_PASSWORD"`
\set app_password       `echo "$COGES_APP_PASSWORD"`
\set relay_password     `echo "$COGES_RELAY_PASSWORD"`
\set analytics_password `echo "$COGES_ANALYTICS_PASSWORD"`

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

-- Relais de l'outbox : le seul composant qui doit voir **toutes** les entreprises.
-- Il n'obtient pourtant aucun privilège de contournement et aucun privilège de
-- table : il n'a qu'EXECUTE sur trois fonctions SECURITY DEFINER (ADR 0032).
CREATE ROLE coges_relay LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    PASSWORD :'relay_password';

-- Rôle analytique (§ 8.11, reporté à la phase 08 par l'ADR 0004) : écrit les
-- projections, lit le transactionnel, pose le même contexte tenant que tout le
-- monde. C'est le seul rôle du projet autorisé à DELETE, et seulement sur les
-- tables analytiques, qui sont intégralement reconstruisibles.
CREATE ROLE coges_analytics LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    PASSWORD :'analytics_password';

-- Propriétaire des fonctions du bus (outbox_claim, outbox_mark_published,
-- active_company_ids). Même raisonnement que coges_auth : seul un propriétaire
-- BYPASSRLS permet à une fonction SECURITY DEFINER de franchir FORCE ROW LEVEL
-- SECURITY. NOLOGIN : la surface de contournement tient en trois fonctions.
CREATE ROLE coges_bus NOLOGIN NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE;

-- coges_owner doit pouvoir transférer la propriété des fonctions à leur rôle final.
-- WITH INHERIT FALSE : aucune élévation implicite, il faut un SET ROLE explicite.
GRANT coges_auth TO coges_owner WITH INHERIT FALSE;
GRANT coges_bus  TO coges_owner WITH INHERIT FALSE;

CREATE DATABASE coges      OWNER coges_owner;
CREATE DATABASE coges_test OWNER coges_owner;

\connect coges
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;
GRANT USAGE ON SCHEMA public TO coges_auth;
GRANT USAGE ON SCHEMA public TO coges_relay;
GRANT USAGE ON SCHEMA public TO coges_analytics;
GRANT USAGE ON SCHEMA public TO coges_bus;

\connect coges_test
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;
GRANT USAGE ON SCHEMA public TO coges_auth;
GRANT USAGE ON SCHEMA public TO coges_relay;
GRANT USAGE ON SCHEMA public TO coges_analytics;
GRANT USAGE ON SCHEMA public TO coges_bus;
