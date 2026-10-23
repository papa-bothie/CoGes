-- Rôle de l'administration de la plateforme (lot admin 1, ADR 0089). À lancer UNE fois
-- par cluster (Neon préprod, puis prod), en `neondb_owner`, AVANT la migration 0026 :
--
--   psql "$NEONDB_OWNER_DSN" -v platform_password="$(openssl rand -hex 24)" \
--        -f deploy/sql/create_platform_role.sql
--
-- Le mot de passe ne va que dans COGES_DATABASE_URL_PLATFORM du fichier d'environnement
-- du VPS (/etc/coges/coges.env) et dans le gestionnaire de mots de passe.
--
-- LOGIN, NOBYPASSRLS : il traverse la RLS par des politiques qui ne nomment que lui, sur
-- des colonnes que la migration 0026 lui accorde une à une. Aucune table commerciale ne
-- lui est ouverte (tests/architecture/test_platform_role_grants.py).

\set ON_ERROR_STOP on

SELECT :'platform_password' <> '' AS password_given \gset
\if :password_given
\else
  \echo 'Donner le mot de passe : -v platform_password=…'
  \quit
\endif

CREATE ROLE coges_app_platform LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
  NOREPLICATION PASSWORD :'platform_password';
