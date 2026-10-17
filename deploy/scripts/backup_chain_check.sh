#!/usr/bin/env bash
# Preuve que la chaîne de sauvegarde marche (ADR 0084), sans aucun envoi réel :
#
#   base source ─backup.sh─▶ faux stockage (dossier local, rclone « local »)
#               ─restore_backup.sh─▶ base vide ─verify_restore.py─▶ vert
#
# Joué par la CI à chaque changement (job « Sauvegarde : chaîne complète ») et en local :
#
#   BACKUP_SOURCE_URL=postgresql://coges_backup:…@localhost:5433/coges_e2e?sslmode=disable \
#   RESTORE_ADMIN_URL=postgresql://postgres:…@localhost:5433/postgres \
#   deploy/scripts/backup_chain_check.sh
#
# BACKUP_SOURCE_URL : base à sauvegarder, lue par coges_backup comme en production.
# RESTORE_ADMIN_URL : superutilisateur du même cluster, qui crée la base vide
#                     `coges_restore` et y restaure (propriétaires des fonctions gardés).
# La clé age est une clé de test, créée puis détruite ici.

set -euo pipefail

: "${BACKUP_SOURCE_URL:?BACKUP_SOURCE_URL manquant}"
: "${RESTORE_ADMIN_URL:?RESTORE_ADMIN_URL manquant}"
SCRIPTS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

restore_url() {
  python3 - "$RESTORE_ADMIN_URL" <<'EOF'
import sys, urllib.parse
parts = urllib.parse.urlsplit(sys.argv[1])
print(urllib.parse.urlunsplit(parts._replace(path="/coges_restore")))
EOF
}
TARGET=$(restore_url)

echo "== clé de test"
age-keygen -o "$WORK/test.key" 2>/dev/null
recipient=$(age-keygen -y "$WORK/test.key")

echo "== sauvegarde (backup.sh, faux stockage local)"
mkdir -p "$WORK/remote"
BACKUP_DATABASE_URL="$BACKUP_SOURCE_URL" \
  BACKUP_ALLOW_LOCAL=1 \
  BACKUP_AGE_RECIPIENT="$recipient" \
  BACKUP_REMOTE="local:$WORK/remote" \
  RCLONE_CONFIG_LOCAL_TYPE=local \
  BACKUP_WORKDIR="$WORK/out" \
  bash -c 'mkdir -p "$BACKUP_WORKDIR" && exec bash "$0"' "$SCRIPTS/backup.sh"
archive=$(find "$WORK/remote" -name 'coges-*.dump.age' | head -1)
[[ -n "$archive" ]] || { echo "aucune sauvegarde produite" >&2; exit 1; }
if age --decrypt --identity /dev/null "$archive" >/dev/null 2>&1; then
  echo "la sauvegarde se lit sans la clé privée" >&2
  exit 1
fi
if strings "$archive" | grep -q "CREATE TABLE"; then
  echo "la sauvegarde n'est pas chiffrée" >&2
  exit 1
fi

echo "== base vide coges_restore"
psql "$RESTORE_ADMIN_URL" -X -q -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS coges_restore" \
  -c "CREATE DATABASE coges_restore OWNER coges_owner"
psql "$TARGET" -X -q -v ON_ERROR_STOP=1 -c "REVOKE ALL ON SCHEMA public FROM PUBLIC"

echo "== restauration et vérifications (restore_backup.sh)"
COGES_PRODUCTION_DB_HOST=production.invalid \
  bash "$SCRIPTS/restore_backup.sh" "$archive" "$WORK/test.key" "$TARGET"

echo "== une seconde restauration est refusée (base non vide)"
if COGES_PRODUCTION_DB_HOST=production.invalid \
  bash "$SCRIPTS/restore_backup.sh" "$archive" "$WORK/test.key" "$TARGET" >/dev/null 2>&1; then
  echo "restore_backup.sh a accepté une base non vide" >&2
  exit 1
fi

psql "$RESTORE_ADMIN_URL" -X -q -c "DROP DATABASE coges_restore"
echo "Chaîne de sauvegarde vérifiée : sauvegarde chiffrée, restaurée, contrôlée."
