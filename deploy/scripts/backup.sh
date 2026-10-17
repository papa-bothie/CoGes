#!/usr/bin/env bash
# Sauvegarde externe chiffrée de la base Neon (ADR 0084), lancée chaque nuit par
# .github/workflows/backup.yml — jamais sur le VPS.
#
#   pg_dump -Fc ──pipe──▶ age -r <clé publique> ──▶ coges-AAAA-MM-JJ-HHMM.dump.age (+ .sha256)
#                                                   └─ rclone ─▶ stockage objet S3 hors Neon
#
# Le dump en clair ne touche jamais un disque : il passe d'un processus à l'autre par un
# tube. La clé PRIVÉE age n'est jamais ici : le workflow ne peut pas relire ce qu'il écrit.
#
# Variables (secrets GitHub) :
#   BACKUP_DATABASE_URL   DSN du rôle coges_backup, sslmode=require
#   BACKUP_AGE_RECIPIENT  clé publique age (age1…)
#   BACKUP_REMOTE         destination rclone, par ex. « coges:coges-sauvegardes/prod »
#   RCLONE_CONFIG_COGES_* configuration rclone du distant « coges » (type s3, clés
#                          d'écriture + liste, sans droit de suppression)
#   BACKUP_PING_URL       facultatif : Healthchecks.io (succès), /fail (échec)
# Facultatif : BACKUP_WORKDIR (répertoire de travail, par défaut un temporaire),
#              BACKUP_MIN_RATIO (défaut 0.5 : taille minimale par rapport à la précédente),
#              BACKUP_ALLOW_LOCAL=1 (preuve locale seulement : base localhost sans TLS).

set -euo pipefail

: "${BACKUP_DATABASE_URL:?BACKUP_DATABASE_URL manquant}"
: "${BACKUP_AGE_RECIPIENT:?BACKUP_AGE_RECIPIENT manquant}"
: "${BACKUP_REMOTE:?BACKUP_REMOTE manquant}"
MIN_RATIO=${BACKUP_MIN_RATIO:-0.5}

ping() {
  # Jamais bloquant, aucune donnée envoyée (comme les pings des tâches, ADR 0077).
  [[ -n "${BACKUP_PING_URL:-}" ]] || return 0
  curl --silent --show-error --max-time 10 --retry 2 --output /dev/null "$1" || true
}

fail() {
  echo "ÉCHEC : $*" >&2
  ping "${BACKUP_PING_URL:-}/fail"
  exit 1
}
trap 'fail "étape interrompue (ligne $LINENO)"' ERR

db_host=$(python3 -c 'import sys,urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).hostname or "")' "$BACKUP_DATABASE_URL")
if [[ "$BACKUP_DATABASE_URL" != *sslmode=require* && "$BACKUP_DATABASE_URL" != *sslmode=verify-full* ]]; then
  # Seule exception : la preuve de la chaîne (backup_chain_check.sh), sur une base locale.
  [[ "${BACKUP_ALLOW_LOCAL:-0}" == 1 && ("$db_host" == localhost || "$db_host" == 127.0.0.1) ]] \
    || fail "BACKUP_DATABASE_URL doit imposer sslmode=require"
fi
[[ "$BACKUP_AGE_RECIPIENT" == age1* ]] || fail "BACKUP_AGE_RECIPIENT n'est pas une clé publique age"

WORKDIR=${BACKUP_WORKDIR:-$(mktemp -d)}
cleanup() { rm -rf "$WORKDIR"; }
[[ -z "${BACKUP_WORKDIR:-}" ]] && trap cleanup EXIT

NAME="coges-$(date -u +%Y-%m-%d-%H%M).dump.age"
FILE="$WORKDIR/$NAME"

echo "1/4 — pg_dump $(pg_dump --version | awk '{print $NF}') chiffré par age → $NAME"
pg_dump --format=custom --no-password --dbname="$BACKUP_DATABASE_URL" \
  | age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" --output "$FILE"
size=$(stat -c %s "$FILE")
((size > 0)) || fail "fichier chiffré vide"
(cd "$WORKDIR" && sha256sum "$NAME" >"$NAME.sha256")
echo "    $((size / 1024)) Kio, sha256 $(cut -c1-16 "$FILE.sha256")…"

echo "2/4 — comparaison à la sauvegarde précédente"
previous=$(rclone lsjson --files-only "$BACKUP_REMOTE" 2>/dev/null \
  | python3 -c 'import json,sys
items=[i for i in json.load(sys.stdin) if i["Name"].endswith(".dump.age")]
items.sort(key=lambda i: i["Name"])
print(items[-1]["Size"] if items else 0)')
if ((previous > 0)); then
  if python3 -c "import sys; sys.exit(0 if $size >= $MIN_RATIO * $previous else 1)"; then
    echo "    précédente : $((previous / 1024)) Kio — taille cohérente"
    too_small=0
  else
    echo "    précédente : $((previous / 1024)) Kio — moins de ${MIN_RATIO} fois : dump tronqué ou base vidée ?"
    too_small=1
  fi
else
  echo "    aucune sauvegarde précédente"
  too_small=0
fi

echo "3/4 — envoi vers $BACKUP_REMOTE"
# --immutable : ne jamais écraser un fichier existant ; aucun droit de suppression ici.
rclone copyto --immutable "$FILE.sha256" "$BACKUP_REMOTE/$NAME.sha256"
rclone copyto --immutable "$FILE" "$BACKUP_REMOTE/$NAME"

echo "4/4 — relecture du fichier distant"
remote_size=$(rclone lsjson --files-only "$BACKUP_REMOTE/$NAME" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["Size"])')
[[ "$remote_size" == "$size" ]] || fail "taille distante $remote_size ≠ $size"
remote_sum=$(rclone cat "$BACKUP_REMOTE/$NAME" | sha256sum | cut -d' ' -f1)
[[ "$remote_sum" == "$(cut -d' ' -f1 "$FILE.sha256")" ]] || fail "sha256 distant différent"
echo "    taille et sha256 identiques"

if ((too_small)); then
  fail "sauvegarde envoyée, mais moins de ${MIN_RATIO} fois la précédente : vérifier la base"
fi
ping "${BACKUP_PING_URL:-}"
echo "Sauvegarde $NAME : OK"
