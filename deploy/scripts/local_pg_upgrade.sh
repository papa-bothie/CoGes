#!/usr/bin/env bash
# Recopie la base locale PostgreSQL 16 dans le nouveau volume PostgreSQL 18 (ADR 0095).
# Lancé par `make db-upgrade-18`, depuis la racine du dépôt, une seule fois.
#
#   ancien volume <projet>_coges_pgdata   ── conteneur postgres:16-alpine ──┐
#                                                           pg_dumpall (client 18)
#   nouveau volume <projet>_coges_pgdata18 ◀── conteneur postgres:18-alpine ──┘ psql
#
# L'ancien volume n'est JAMAIS modifié ni supprimé : il reste là tant que vous ne le
# supprimez pas vous-même (`docker volume rm <projet>_coges_pgdata`). Le serveur qui
# l'utilise est arrêté avant la copie (deux serveurs sur un même volume l'abîmeraient).
# Refus si le nouveau volume contient déjà des données (`make up` déjà lancé sous 18) :
# il faut alors le vider soi-même, ou repartir de zéro (make up && make migrate &&
# make seed-demo).
#
# Variables : POSTGRES_PASSWORD (le .env, exporté par make), COMPOSE_PROJECT_NAME
# (facultatif, comme docker compose).

set -euo pipefail

FROM_IMAGE=postgres:16-alpine
TO_IMAGE=postgres:18-alpine
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD manquant (lancer par make db-upgrade-18)}"

die() {
  echo "ÉCHEC : $*" >&2
  exit 1
}

project=$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
OLD="${project}_coges_pgdata"
NEW="${project}_coges_pgdata18"
NET="${project}-pg-upgrade"
OLD_CT="${project}-pg-upgrade-16"
NEW_CT="${project}-pg-upgrade-18"
WORK=$(mktemp -d)
created_new=0

cleanup() {
  status=$?
  docker rm -f "$OLD_CT" "$NEW_CT" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  if ((status != 0 && created_new)); then
    # Seul le volume créé par ce lancement est retiré ; l'ancien n'est jamais touché.
    docker volume rm "$NEW" >/dev/null 2>&1 || true
    echo "Nouveau volume $NEW retiré ; l'ancien $OLD est intact." >&2
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

docker volume inspect "$OLD" >/dev/null 2>&1 \
  || die "ancien volume $OLD absent : rien à recopier (make up && make migrate && make seed-demo)"
if docker volume inspect "$NEW" >/dev/null 2>&1; then
  content=$(docker run --rm -v "$NEW:/v:ro" "$TO_IMAGE" ls -A /v)
  [[ -z "$content" ]] \
    || die "le volume $NEW contient déjà des données ; le vider vous-même avant de relancer (docker compose down && docker volume rm $NEW)"
else
  # Étiquettes de docker compose : il reconnaîtra ce volume comme le sien.
  docker volume create --label "com.docker.compose.project=$project" \
    --label com.docker.compose.volume=coges_pgdata18 "$NEW" >/dev/null
  created_new=1
fi

echo "1/4 — arrêt du serveur qui utilise $OLD"
running=$(docker ps -q --filter "volume=$OLD")
if [[ -n "$running" ]]; then
  # shellcheck disable=SC2086 # une liste d'identifiants
  docker stop $running >/dev/null
fi

echo "2/4 — serveurs temporaires : 16 sur $OLD, 18 sur $NEW"
docker network create "$NET" >/dev/null
docker run -d --name "$OLD_CT" --network "$NET" \
  -v "$OLD:/var/lib/postgresql/data" "$FROM_IMAGE" >/dev/null
docker run -d --name "$NEW_CT" --network "$NET" -e POSTGRES_PASSWORD \
  -v "$NEW:/var/lib/postgresql" "$TO_IMAGE" >/dev/null
for ct in "$OLD_CT" "$NEW_CT"; do
  # Par TCP : pendant l'initialisation, le serveur 18 n'écoute que sur sa socket.
  for _ in $(seq 60); do
    docker exec "$ct" pg_isready -q -h 127.0.0.1 -U postgres && continue 2
    sleep 1
  done
  docker logs "$ct" | tail -20 >&2
  die "le serveur $ct ne répond pas"
done

echo "3/4 — pg_dumpall (client 18) depuis 16, restauré dans 18"
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$NEW_CT" \
  pg_dumpall -h "$OLD_CT" -U postgres --no-password \
  | docker exec -i "$NEW_CT" psql -X -q -U postgres -d postgres >/dev/null 2>"$WORK/errors"
# Le seul refus attendu : le superutilisateur, déjà créé par l'image 18.
unexpected=$(grep 'ERROR' "$WORK/errors" | grep -v 'role "postgres" already exists' || true)
[[ -z "$unexpected" ]] || { echo "$unexpected" >&2; die "erreurs pendant la restauration"; }

echo "4/4 — comparaison ligne à ligne (rôles, bases, lignes de chaque table)"
inventory() {
  local ct=$1 host=$2 db
  docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$ct" psql -X -A -t -h "$host" -U postgres \
    -d postgres -c "SELECT rolname FROM pg_roles WHERE rolname NOT LIKE 'pg\_%' ORDER BY 1"
  for db in $(docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$ct" psql -X -A -t -h "$host" \
    -U postgres -d postgres -c "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1"); do
    echo "== $db"
    # Superutilisateur : la RLS ne s'applique pas, chaque ligne est comptée.
    docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$ct" psql -X -A -t -h "$host" -U postgres \
      -d "$db" -c "SELECT schemaname || '.' || tablename || ' ' || (xpath('/row/c/text()',
        query_to_xml(format('SELECT count(*) AS c FROM %I.%I', schemaname, tablename),
        false, true, '')))[1]::text
        FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY 1"
  done
}
inventory "$NEW_CT" "$OLD_CT" >"$WORK/old.txt"
inventory "$NEW_CT" 127.0.0.1 >"$WORK/new.txt"
diff -u "$WORK/old.txt" "$WORK/new.txt" >&2 || die "la copie diffère de l'original"
echo "    $(grep -c '^== ' "$WORK/new.txt") bases, $(grep -vc '^== ' "$WORK/new.txt") rôles et tables identiques"

created_new=0
echo "Copie vérifiée. L'ancien volume $OLD est conservé ; une fois sûr de vous :"
echo "  docker volume rm $OLD"
