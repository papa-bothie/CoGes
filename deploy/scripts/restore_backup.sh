#!/usr/bin/env bash
# Restaure une sauvegarde chiffrée dans une base VIDE, puis la vérifie (ADR 0084).
#
#   deploy/scripts/restore_backup.sh <coges-….dump.age> <clé-privée-age> <DSN cible>
#
# Exemple (base de secours sur une branche Neon, ou PostgreSQL local) :
#   COGES_PRODUCTION_DB_HOST=ep-xxx.eu-central-1.aws.neon.tech \
#   deploy/scripts/restore_backup.sh ~/secours/coges-2026-10-18-0215.dump.age ~/coges-backup.key \
#     "postgresql://coges_restorer:…@ep-yyy.eu-central-1.aws.neon.tech/coges_secours?sslmode=require"
#
# Refus :
#   • sha256 absent ou différent (le fichier .sha256 doit être à côté) ;
#   • manifeste `.manifest.json` absent (RESTORE_WITHOUT_MANIFEST=1 pour une sauvegarde
#     antérieure à l'ADR 0088) ;
#   • COGES_PRODUCTION_DB_HOST non donné, ou cible sur cet hôte : on ne restaure jamais
#     par-dessus la production ;
#   • base cible non vide (une table, un type, une fonction ou une séquence dans le
#     schéma public, hors extensions) : après un échec, recréer la base ;
#   • coges_auth, coges_bus, coges_ops ou coges_billing absent de la cible, ou sans USAGE
#     et CREATE sur son schéma public (le message donne le GRANT à lancer) ;
#   • pg_restore d'une version majeure plus ancienne que le pg_dump noté dans le
#     manifeste (ADR 0095 ; manifeste sans version : avertissement seulement).
#
# Le déchiffrement passe deux fois par un tube : `pg_restore --list` lit le sommaire, dont
# restore_toc_filter.py retire les droits internes à Neon (cloud_admin, neon_superuser,
# neon_*), puis `pg_restore --use-list` restaure le reste. La sauvegarde en clair ne
# touche jamais le disque ; seul le sommaire (noms d'objets, aucune donnée) y passe, dans
# un dossier temporaire effacé à la sortie. La clé privée est lue depuis le fichier
# donné, jamais copiée.
# Les rôles du cluster (coges_owner, coges_app, coges_auth, coges_bus, coges_ops…)
# doivent exister sur la cible, et l'utilisateur du DSN pouvoir les emprunter
# (superutilisateur en local ; sur Neon, coges_restorer, voir docs/runbooks/sauvegarde.md).

set -euo pipefail

if [[ $# -ne 3 ]]; then
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi
ARCHIVE=$1
KEY=$2
TARGET=$3
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

die() {
  echo "REFUS : $*" >&2
  exit 1
}

[[ -f "$ARCHIVE" ]] || die "sauvegarde introuvable : $ARCHIVE"
[[ -r "$KEY" ]] || die "clé privée illisible : $KEY"

echo "1/4 — empreinte"
SUM_FILE="$ARCHIVE.sha256"
[[ -f "$SUM_FILE" ]] || die "empreinte absente : $SUM_FILE"
expected=$(cut -d' ' -f1 "$SUM_FILE")
actual=$(sha256sum "$ARCHIVE" | cut -d' ' -f1)
[[ "$expected" == "$actual" ]] || die "sha256 différent : fichier abîmé ou modifié"
echo "    sha256 conforme"
MANIFEST="$ARCHIVE.manifest.json"
manifest_args=(--manifest "$MANIFEST")
if [[ ! -f "$MANIFEST" ]]; then
  # Sauvegarde antérieure à l'ADR 0088 : il faut le dire, sinon on refuse.
  [[ "${RESTORE_WITHOUT_MANIFEST:-0}" == 1 ]] \
    || die "manifeste absent : $MANIFEST (RESTORE_WITHOUT_MANIFEST=1 pour une ancienne sauvegarde)"
  manifest_args=()
fi
# pg_restore lit les archives des versions précédentes, jamais celles d'une version
# majeure plus récente : le manifeste dit quel pg_dump a produit le fichier (ADR 0095).
command -v pg_restore >/dev/null || die "pg_restore introuvable : installer le client PostgreSQL"
restore_version=$(pg_restore --version | sed -nE 's/^pg_restore \(PostgreSQL\) ([0-9][0-9a-z.]*).*/\1/p')
restore_major=${restore_version%%[!0-9]*}
[[ -n "$restore_major" ]] || die "version de pg_restore illisible"
dump_version=""
if [[ -f "$MANIFEST" ]]; then
  dump_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("pg_dump_version", ""))' "$MANIFEST")
fi
if [[ -z "$dump_version" ]]; then
  echo "AVERTISSEMENT : version de pg_dump inconnue (sauvegarde antérieure à l'ADR 0095) ;" \
    "pg_restore $restore_version doit être au moins de la version majeure du serveur sauvegardé" >&2
else
  dump_major=${dump_version%%[!0-9]*}
  [[ "$dump_major" =~ ^[0-9]+$ ]] || die "version de pg_dump illisible dans le manifeste : $dump_version"
  ((restore_major >= dump_major)) \
    || die "pg_restore $restore_major trop ancien pour une sauvegarde de pg_dump $dump_major : installer postgresql-client-$dump_major"
  echo "    pg_restore $restore_version, sauvegarde de pg_dump $dump_version"
fi

echo "2/4 — cible"
: "${COGES_PRODUCTION_DB_HOST:?donner COGES_PRODUCTION_DB_HOST (hôte de la base de production, pour ne jamais l écraser)}"
target_host=$(python3 -c 'import sys,urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).hostname or "")' "$TARGET")
[[ -n "$target_host" ]] || die "hôte de la cible illisible"
[[ "${target_host,,}" != "${COGES_PRODUCTION_DB_HOST,,}" ]] \
  || die "la cible est la base de production ($target_host)"
# Un premier essai interrompu laisse des types, fonctions ou séquences sans aucune table :
# pg_restore échouerait alors plus loin sur « already exists ». Les objets d'une extension
# (pg_trgm installé d'avance) ne comptent pas : la sauvegarde les recrée « IF NOT EXISTS ».
counts=$(psql "$TARGET" -X -A -t -F ' ' -v ON_ERROR_STOP=1 -c "
  WITH own AS (
    SELECT objid FROM pg_depend WHERE deptype = 'e'
  )
  SELECT
    (SELECT count(*) FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace
       AND c.relkind IN ('r', 'p') AND c.oid NOT IN (SELECT objid FROM own)),
    (SELECT count(*) FROM pg_type t WHERE t.typnamespace = 'public'::regnamespace
       AND t.typcategory <> 'A' AND t.oid NOT IN (SELECT objid FROM own)
       AND (t.typrelid = 0
            OR (SELECT relkind FROM pg_class WHERE oid = t.typrelid) = 'c')),
    (SELECT count(*) FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace
       AND p.oid NOT IN (SELECT objid FROM own)),
    (SELECT count(*) FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace
       AND c.relkind = 'S' AND c.oid NOT IN (SELECT objid FROM own))")
read -r n_tables n_types n_functions n_sequences <<<"$counts"
[[ "$n_tables $n_types $n_functions $n_sequences" == "0 0 0 0" ]] \
  || die "la base cible n'est pas vide (dans public : $n_tables table(s), $n_types type(s)," \
    "$n_functions fonction(s), $n_sequences séquence(s)) ; la supprimer et la recréer"
echo "    $target_host, base vide"
# pg_restore crée chaque objet puis le donne à son propriétaire : ALTER … OWNER TO exige que
# ce rôle ait CREATE sur le schéma (et USAGE pour l'atteindre). coges_owner possède public.
missing=$(psql "$TARGET" -X -A -t -F ' ' -v ON_ERROR_STOP=1 -c "
  SELECT r, state FROM (
    SELECT r, CASE
      WHEN NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN 'absent'
      WHEN has_schema_privilege(r, 'public', 'USAGE')
       AND has_schema_privilege(r, 'public', 'CREATE') THEN 'ok'
      ELSE 'droits' END AS state
    FROM unnest(ARRAY['coges_auth', 'coges_bus', 'coges_ops', 'coges_billing']) AS r
  ) roles WHERE state <> 'ok' ORDER BY r")
absent=$(awk '$2 == "absent" { print $1 }' <<<"$missing" | paste -sd ' ' -)
[[ -z "$absent" ]] \
  || die "rôle(s) absent(s) de la cible : $absent ; les créer d'abord (docs/runbooks/sauvegarde.md)"
lacking=$(awk '$2 == "droits" { print $1 }' <<<"$missing" | paste -sd ',' - | sed 's/,/, /g')
[[ -z "$lacking" ]] \
  || die "$lacking sans USAGE et CREATE sur le schéma public de la cible ; lancer, en" \
    "propriétaire de la base : GRANT USAGE, CREATE ON SCHEMA public TO $lacking;"
echo "    coges_auth, coges_bus, coges_ops, coges_billing : USAGE et CREATE sur public"

echo "3/4 — sommaire, déchiffrement et restauration"
# pg_restore --list peut s'arrêter avant la fin du flux : age reçoit alors SIGPIPE (141).
set +e
age --decrypt --identity "$KEY" "$ARCHIVE" | pg_restore --list >"$WORK/sommaire.list"
statuses=("${PIPESTATUS[@]}")
set -e
((statuses[0] == 0 || statuses[0] == 141)) || die "déchiffrement impossible (clé privée ?)"
((statuses[1] == 0)) || die "sommaire de la sauvegarde illisible"
python3 "$SCRIPT_DIR/restore_toc_filter.py" "$WORK/restaurer.list" <"$WORK/sommaire.list" \
  || die "sommaire de la sauvegarde illisible"
age --decrypt --identity "$KEY" "$ARCHIVE" \
  | pg_restore --dbname="$TARGET" --exit-on-error --no-password --use-list="$WORK/restaurer.list"
echo "    restauration terminée"

echo "4/4 — vérifications"
python3 "$SCRIPT_DIR/verify_restore.py" "${manifest_args[@]}" "$TARGET"
