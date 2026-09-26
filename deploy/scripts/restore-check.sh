#!/usr/bin/env bash
# Vérification de la procédure de restauration (décision 16 : « restauration testée »).
#
# Rejoue, sur le PostgreSQL local de docker compose, ce que fait une restauration :
#   1. sauvegarde logique de la base source (pg_dump, format custom) ;
#   2. restauration dans une base neuve `coges_restore`, propriétaire coges_owner ;
#   3. contrôles : révision Alembic identique, nombre de lignes identique sur les
#      tables clés, RLS toujours FORCE, et `coges_app` sans contexte ne voit rien.
#
# Côté Neon, la restauration se fait par PITR dans une branche (README-infra) ; ce
# script sert aussi à vérifier une telle branche : SOURCE_DB et RESTORE_URL pointent
# alors vers Neon.
#
# Usage : deploy/scripts/restore-check.sh   (depuis la racine, après `make up`)
set -euo pipefail

cd "$(dirname "$0")/../.."
set -a; [ -f .env ] && . ./.env; set +a

SOURCE_DB="${SOURCE_DB:-coges}"
TARGET_DB="coges_restore"
PG="docker compose exec -T -e PGPASSWORD=${POSTGRES_PASSWORD} postgres"
DUMP=/tmp/coges-restore-check.dump

echo "1/3 — sauvegarde de ${SOURCE_DB}"
$PG pg_dump -U postgres -Fc -d "$SOURCE_DB" -f "$DUMP"

echo "2/3 — restauration dans ${TARGET_DB}"
$PG psql -v ON_ERROR_STOP=1 -U postgres -d postgres -q \
  -c "DROP DATABASE IF EXISTS ${TARGET_DB}" \
  -c "CREATE DATABASE ${TARGET_DB} OWNER coges_owner"
$PG psql -v ON_ERROR_STOP=1 -U postgres -d "$TARGET_DB" -q \
  -c "REVOKE ALL ON SCHEMA public FROM PUBLIC"
# Propriétaires conservés : `auth_lookup` doit rester à coges_auth et les fonctions du
# bus à coges_bus, sans quoi la connexion et le relais ne franchiraient plus la RLS.
$PG pg_restore -U postgres -d "$TARGET_DB" --exit-on-error "$DUMP"

echo "3/3 — contrôles"
query() { $PG psql -U postgres -d "$1" -Atq -c "$2"; }
failures=0
check() {
  if [ "$2" = "$3" ]; then echo "  OK   $1 ($2)"; else echo "  ÉCHEC $1 : source=$2 restaurée=$3"; failures=$((failures+1)); fi
}
check "révision Alembic" "$(query "$SOURCE_DB" 'SELECT version_num FROM alembic_version')" \
                         "$(query "$TARGET_DB" 'SELECT version_num FROM alembic_version')"
# Le superutilisateur du conteneur franchit la RLS : il compte toutes les entreprises.
for table in companies users products inventory_movements sales payments debts audit_logs business_events; do
  check "lignes de ${table}" "$(query "$SOURCE_DB" "SELECT count(*) FROM ${table}")" \
                             "$(query "$TARGET_DB" "SELECT count(*) FROM ${table}")"
done
check "tables sans RLS FORCE" "0" \
  "$(query "$TARGET_DB" "SELECT count(*) FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'company_id' WHERE c.relkind IN ('r','p') AND c.relnamespace = 'public'::regnamespace AND NOT c.relispartition AND NOT (c.relrowsecurity AND c.relforcerowsecurity)")"
check "propriétaire de auth_lookup" "coges_auth" \
  "$(query "$TARGET_DB" "SELECT proowner::regrole FROM pg_proc WHERE proname = 'auth_lookup'")"
check "lignes visibles par coges_app sans contexte" "0" \
  "$($PG sh -c "PGPASSWORD=${COGES_APP_PASSWORD} psql -h localhost -U coges_app -d ${TARGET_DB} -Atq -c 'SELECT count(*) FROM products'")"

$PG psql -U postgres -d postgres -q -c "DROP DATABASE ${TARGET_DB}"
$PG rm -f "$DUMP"
if [ "$failures" -gt 0 ]; then echo "Restauration : ${failures} contrôle(s) en échec"; exit 1; fi
echo "Restauration vérifiée."
