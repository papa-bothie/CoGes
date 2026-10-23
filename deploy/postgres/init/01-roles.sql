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
\set backup_password    `echo "${COGES_BACKUP_PASSWORD:-}"`
\set platform_password  `echo "${COGES_PLATFORM_PASSWORD:-change-me-platform}"`

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

-- Propriétaire des fonctions de surveillance (job_run_start, job_run_finish,
-- job_runs_latest, purge_job_runs) : seul à atteindre `job_runs`, journal des tâches
-- planifiées (ADR 0077). Même patron que coges_bus : NOLOGIN, BYPASSRLS confiné à
-- quatre fonctions et à une table.
CREATE ROLE coges_ops NOLOGIN NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE;

-- Sauvegarde externe (ADR 0084) : pg_dump doit lire malgré FORCE ROW LEVEL SECURITY.
-- Seul rôle connectable avec BYPASSRLS (exception nommée de T36), SELECT seul (révision
-- 0023), jamais sur le VPS. Sans COGES_BACKUP_PASSWORD, le mot de passe est vide : le rôle
-- existe, personne ne s'y connecte.
CREATE ROLE coges_backup LOGIN BYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    NOREPLICATION CONNECTION LIMIT 2 PASSWORD :'backup_password';
ALTER ROLE coges_backup SET default_transaction_read_only = on;

-- Administration de la plateforme (lot admin 1, ADR 0089) : lit les métadonnées des
-- entreprises (nom, slug, statut, comptes) et rien d'autre. Ni BYPASSRLS ni privilège
-- sur une table commerciale : la révision 0026 lui donne des GRANT colonne par colonne,
-- et un test d'architecture vérifie qu'elle n'en donne jamais plus.
CREATE ROLE coges_app_platform LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    PASSWORD :'platform_password';

-- coges_owner doit pouvoir transférer la propriété des fonctions à leur rôle final.
-- WITH INHERIT FALSE : aucune élévation implicite, il faut un SET ROLE explicite.
GRANT coges_auth TO coges_owner WITH INHERIT FALSE;
GRANT coges_bus  TO coges_owner WITH INHERIT FALSE;
GRANT coges_ops  TO coges_owner WITH INHERIT FALSE;

CREATE DATABASE coges      OWNER coges_owner;
CREATE DATABASE coges_test OWNER coges_owner;
-- Parcours Playwright (ADR 0059) ; recréée avant chaque suite par `make e2e-reset`.
CREATE DATABASE coges_e2e  OWNER coges_owner;

\connect coges
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;
GRANT USAGE ON SCHEMA public TO coges_auth;
GRANT USAGE ON SCHEMA public TO coges_relay;
GRANT USAGE ON SCHEMA public TO coges_analytics;
GRANT USAGE ON SCHEMA public TO coges_bus;
GRANT USAGE ON SCHEMA public TO coges_app_platform;

\connect coges_test
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;
GRANT USAGE ON SCHEMA public TO coges_auth;
GRANT USAGE ON SCHEMA public TO coges_relay;
GRANT USAGE ON SCHEMA public TO coges_analytics;
GRANT USAGE ON SCHEMA public TO coges_bus;
GRANT USAGE ON SCHEMA public TO coges_app_platform;

\connect coges_e2e
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;
GRANT USAGE ON SCHEMA public TO coges_auth;
GRANT USAGE ON SCHEMA public TO coges_relay;
GRANT USAGE ON SCHEMA public TO coges_analytics;
GRANT USAGE ON SCHEMA public TO coges_bus;
GRANT USAGE ON SCHEMA public TO coges_app_platform;
