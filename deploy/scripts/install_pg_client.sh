#!/usr/bin/env bash
# Installe le client PostgreSQL d'une version majeure donnée depuis le dépôt officiel
# PGDG, et vérifie que c'est bien lui qui répond (ADR 0095).
#
#   deploy/scripts/install_pg_client.sh 18
#
# Ubuntu 24.04 ne fournit que le client 16, et pg_dump refuse un serveur d'une version
# majeure plus récente. Joué par .github/workflows/backup.yml et par le job « Sauvegarde :
# chaîne complète » de la CI ; utilisable tel quel sur un poste Ubuntu ou Debian.
#
# Le répertoire bin/ de cette version passe en tête du PATH (dans $GITHUB_PATH sur un
# runner) : le pg_wrapper de Debian pourrait sinon choisir le client 16 préinstallé.

set -euo pipefail

MAJOR=${1:?donner la version majeure, par ex. 18}
[[ "$MAJOR" =~ ^[0-9]+$ ]] || { echo "ÉCHEC : version majeure invalide : $MAJOR" >&2; exit 1; }

sudo apt-get update -qq
sudo apt-get install -y -qq postgresql-common >/dev/null
# Ajoute le dépôt apt.postgresql.org et sa clé de signature, sans question.
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y >/dev/null
sudo apt-get install -y -qq "postgresql-client-$MAJOR" >/dev/null

BIN="/usr/lib/postgresql/$MAJOR/bin"
[[ -x "$BIN/pg_dump" ]] || { echo "ÉCHEC : $BIN/pg_dump absent après installation" >&2; exit 1; }
if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$BIN" >>"$GITHUB_PATH"
fi
export PATH="$BIN:$PATH"

for tool in pg_dump pg_restore psql; do
  # « pg_dump (PostgreSQL) 18.1 (Ubuntu 18.1-1.pgdg24.04+1) » → 18
  line=$("$tool" --version)
  version=$(sed -nE 's/^[a-z_]+ \(PostgreSQL\) ([0-9]+).*/\1/p' <<<"$line")
  echo "$line"
  [[ "$version" == "$MAJOR" ]] \
    || { echo "ÉCHEC : $tool répond en version ${version:-?}, $MAJOR attendue" >&2; exit 1; }
done
