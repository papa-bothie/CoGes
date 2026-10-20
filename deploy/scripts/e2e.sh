#!/usr/bin/env bash
# Base dédiée aux parcours Playwright (ADR 0059) : `coges_e2e`, jamais `coges`, la
# préproduction ou Neon.
#
#   deploy/scripts/e2e.sh reset   # recrée coges_e2e : migrations, démo (`demo`) et entreprise `e2e` vide
#   deploy/scripts/e2e.sh api     # API sur :8100, branchée sur coges_e2e, débit non limité
#   deploy/scripts/e2e.sh front   # front sur :3100, branché sur l'API e2e (build séparé)
#   deploy/scripts/e2e.sh admin   # administration (frontend-admin) sur :3200, même API e2e
#   deploy/scripts/e2e.sh maquette        # ajoute l'entreprise `maquette` (seed de la maquette v2)
#   deploy/scripts/e2e.sh maquette-api    # API sur :8101, heure figée au 6 octobre 2026 10 h 45
#   deploy/scripts/e2e.sh maquette-front  # front sur :3101, branché sur l'API de la maquette
#
# Les DSN viennent du .env local (exporté par le Makefile, ou lu ici) ; seul le nom de la
# base change. Un DSN dont l'hôte n'est pas local fait tout échouer avant la moindre
# commande : ce script ne peut pas viser une base distante.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Le .env local complète l'environnement sans jamais remplacer une variable déjà fixée
# (par le Makefile ou par l'appelant).
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]] || continue
    key=${BASH_REMATCH[1]} value=${BASH_REMATCH[2]}
    value=${value%\"} value=${value#\"}
    [ -n "${!key+x}" ] || export "$key=$value"
  done <.env
fi

E2E_DB=coges_e2e
E2E_API_PORT="${E2E_API_PORT:-8100}"
E2E_FRONT_PORT="${E2E_FRONT_PORT:-3100}"
E2E_ADMIN_PORT="${E2E_ADMIN_PORT:-3200}"
# Compte de l'administration des parcours (ADR 0089), sans valeur hors de coges_e2e.
E2E_ADMIN_EMAIL=admin@e2e.example.com
E2E_ADMIN_PASSWORD=admin-coges-e2e-2026
MAQUETTE_API_PORT="${MAQUETTE_API_PORT:-8101}"
MAQUETTE_FRONT_PORT="${MAQUETTE_FRONT_PORT:-3101}"
# Le moment des captures de la maquette v2 (ADR 0065), repris de app/seed_maquette.py.
MAQUETTE_NOW="2026-10-06T10:45:00+00:00"

die() {
  echo "e2e : $*" >&2
  exit 1
}

# postgresql+psycopg://rôle:secret@localhost:5433/coges -> …/coges_e2e, hôte local exigé.
# Le contrôle se fait dans le shell principal, avant toute commande : un `die` dans une
# substitution `$(…)` ne quitterait que le sous-shell.
LOCAL_PG='^postgresql(\+psycopg)?://[^@]+@(localhost|127\.0\.0\.1)(:[0-9]+)?/[A-Za-z0-9_]+$'
for var in COGES_DATABASE_URL_OWNER COGES_DATABASE_URL_APP COGES_DATABASE_URL_RELAY \
  COGES_DATABASE_URL_ANALYTICS COGES_DATABASE_URL_PLATFORM; do
  url=${!var:-}
  [ -n "$url" ] || die "$var manquant (copier .env.example vers .env)"
  [[ "$url" =~ $LOCAL_PG ]] ||
    die "$var doit viser une base PostgreSQL locale (localhost), jamais une base distante"
  export "$var=${url%/*}/$E2E_DB"
done

# Redis local, base n° 1 : le cache et les compteurs des tests ne croisent pas ceux du
# développement (base n° 0).
redis=${COGES_REDIS_URL:-redis://localhost:6379/0}
[[ "$redis" =~ ^redis://([^@]*@)?(localhost|127\.0\.0\.1)(:[0-9]+)?(/[0-9]+)?$ ]] ||
  die "COGES_REDIS_URL doit viser un Redis local"
[[ "$redis" =~ /[0-9]+$ ]] && redis=${redis%/*}
export COGES_REDIS_URL="$redis/1"

# Front Next en mode développement, arrêté avec ses enfants. `pnpm exec next dev` laissait
# un `next-server` orphelin qui gardait la sortie ouverte : Playwright attendait sa
# fermeture sans fin à la fin de la suite. Ici, le script attend `next` et, au signal de
# Playwright, termine `next` et ses processus enfants.
run_front() {
  local dist=$1 api_port=$2 port=$3 app=${4:-frontend}
  cd "$app"
  COGES_NEXT_DIST_DIR=$dist COGES_API_URL="http://localhost:$api_port" \
    ./node_modules/.bin/next dev --port "$port" &
  local next_pid=$!
  trap 'pkill -TERM -P "$next_pid" 2>/dev/null; kill -TERM "$next_pid" 2>/dev/null' TERM INT EXIT
  wait "$next_pid"
}

case "${1:-}" in
  reset)
    echo "e2e : recréation de la base $E2E_DB"
    docker compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -q <<SQL
DROP DATABASE IF EXISTS $E2E_DB WITH (FORCE);
CREATE DATABASE $E2E_DB OWNER coges_owner;
\connect $E2E_DB
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO coges_app;
GRANT USAGE ON SCHEMA public TO coges_auth;
GRANT USAGE ON SCHEMA public TO coges_relay;
GRANT USAGE ON SCHEMA public TO coges_analytics;
GRANT USAGE ON SCHEMA public TO coges_bus;
GRANT USAGE ON SCHEMA public TO coges_app_platform;
SQL
    uv run --directory backend alembic upgrade head
    seeded=$(uv run --directory backend python -m app.seed)
    echo "$seeded"
    company=$(awk '/créée :/ { print $NF }' <<<"$seeded")
    [ -n "$company" ] || die "identifiant de l'entreprise de démonstration introuvable"
    # Sans relais ni worker, rien ne construit les agrégats ni les recommandations : on
    # exécute ici, une fois, ce que la nuit ferait (tableau de bord, analytics, Intelligence).
    uv run --directory backend python -c \
      "from app.workers.tasks.analytics import rebuild_recent_facts; rebuild_recent_facts('$company', 91)"
    uv run --directory backend python -m app.cli run-intelligence --company-id "$company" --train
    # Les parcours qui écrivent ont leur propre entreprise, vide (ADR 0060) : la démo ne
    # reçoit jamais d'« Article E2E », et les captures la montrent telle quelle.
    uv run --directory backend python -m app.cli create-company --name "Parcours e2e" \
      --slug e2e --manager-email gerant@e2e.example.com --manager-name "Gérant des parcours" \
      --password demo-coges-2026
    # Administration (ADR 0089) : un compte de l'équipe, et une entreprise que ses parcours
    # suspendent puis réactivent sans toucher aux autres.
    uv run --directory backend python -m app.cli create-platform-user \
      --email "$E2E_ADMIN_EMAIL" --name "Équipe des parcours" --role administrator \
      --password "$E2E_ADMIN_PASSWORD"
    uv run --directory backend python -m app.cli create-company --name "Parcours administration" \
      --slug admin-e2e --manager-email gerant@admin-e2e.example.com \
      --manager-name "Gérant suspendu" --password demo-coges-2026
    # L'épicerie de la maquette v2, à part : la démo et `e2e` ne changent pas (ADR 0065).
    uv run --directory backend python -m app.seed_maquette --intelligence
    ;;
  maquette)
    shift
    uv run --directory backend python -m app.seed_maquette --intelligence "$@"
    ;;
  maquette-api)
    # Une API à part, à l'heure figée : les autres parcours gardent l'heure réelle.
    export COGES_RATE_LIMIT_IP_PER_MINUTE=0
    export COGES_RATE_LIMIT_TENANT_PER_MINUTE=0
    export COGES_RATE_LIMIT_LOGIN_PER_MINUTE=0
    export COGES_LOGIN_THROTTLE_FREE_FAILURES=1000000
    export COGES_FROZEN_NOW="$MAQUETTE_NOW"
    # Le cache du tableau de bord ne doit pas mêler l'heure figée et l'heure réelle.
    export COGES_REDIS_URL="${COGES_REDIS_URL%/*}/2"
    exec uv run --directory backend uvicorn app.main:app --port "$MAQUETTE_API_PORT"
    ;;
  maquette-front)
    run_front .next-maquette "$MAQUETTE_API_PORT" "$MAQUETTE_FRONT_PORT"
    ;;
  api)
    # Limite à 0 = désactivée (app/core/rate_limit.py) : une suite enchaîne des dizaines de
    # connexions depuis la même IP, ce que la limite de connexion refuserait.
    export COGES_RATE_LIMIT_IP_PER_MINUTE=0
    export COGES_RATE_LIMIT_TENANT_PER_MINUTE=0
    export COGES_RATE_LIMIT_LOGIN_PER_MINUTE=0
    # Freinage par compte (ADR 0078) hors d'atteinte : les refus volontaires des parcours
    # s'additionneraient d'une suite à l'autre sur les mêmes comptes.
    export COGES_LOGIN_THROTTLE_FREE_FAILURES=1000000
    export COGES_LOGIN_THROTTLE_ALERT_AFTER=1000000
    exec uv run --directory backend uvicorn app.main:app --port "$E2E_API_PORT"
    ;;
  front)
    # Répertoire de build distinct : le front de développement (:3000, .next) continue de
    # tourner à côté sans conflit.
    run_front .next-e2e "$E2E_API_PORT" "$E2E_FRONT_PORT"
    ;;
  admin)
    run_front .next-e2e "$E2E_API_PORT" "$E2E_ADMIN_PORT" frontend-admin
    ;;
  *)
    die "usage : $0 reset|api|front|admin|maquette|maquette-api|maquette-front"
    ;;
esac
