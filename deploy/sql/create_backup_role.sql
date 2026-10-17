-- Rôle de la sauvegarde externe chiffrée (ADR 0084). À lancer UNE fois par cluster
-- (Neon préprod, puis prod), en `neondb_owner`, AVANT la migration 0023 :
--
--   psql "$NEONDB_OWNER_DSN" -v backup_password="$(openssl rand -base64 36)" \
--        -f deploy/sql/create_backup_role.sql
--
-- Le mot de passe ne va que dans le secret GitHub BACKUP_DATABASE_URL (et le gestionnaire
-- de mots de passe). Jamais sur le VPS.
--
-- Vérifié le 2026-10-17 sur le cluster de préprod : `neondb_owner` a BYPASSRLS (hérité de
-- neon_superuser) et peut donc le donner ; `coges_auth`, `coges_bus` et `coges_ops` en
-- sont déjà dotés.
--
-- LOGIN BYPASSRLS : seule exception à « aucun rôle connectable ne franchit la RLS » (T36),
-- parce que pg_dump ne verrait aucune ligne sans elle. Les droits sont posés par la
-- migration 0023 : SELECT seul, sur le schéma public. Aucun autre attribut.

\set ON_ERROR_STOP on

SELECT :'backup_password' <> '' AS password_given \gset
\if :password_given
\else
  \echo 'Donner le mot de passe : -v backup_password=…'
  \quit
\endif

CREATE ROLE coges_backup LOGIN BYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION CONNECTION LIMIT 2 PASSWORD :'backup_password';
-- Lecture seule même si un droit d'écriture lui était donné par erreur.
ALTER ROLE coges_backup SET default_transaction_read_only = on;
