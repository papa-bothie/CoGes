#!/usr/bin/env bash
# Base dédiée aux parcours Playwright (ADR 0059) : `coges_e2e`, jamais `coges`, la
# préproduction ou Neon.
#
#   deploy/scripts/e2e.sh reset   # recrée coges_e2e : migrations, démo (`demo`) et entreprise `e2e` vide
#   deploy/scripts/e2e.sh api     # API sur :8100, branchée sur coges_e2e, débit non limité
#   deploy/scripts/e2e.sh front   # front sur :3100, branché sur l'API e2e (build séparé)
#   deploy/scripts/e2e.sh admin   # administration (frontend-admin) sur :3200, même API e2e
#   deploy/scripts/e2e.sh system healthy|missing-heartbeat   # état de la zone B (ADR 0090)
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
# Cloudflare Access simulé (ADR 0104) : clé de test, jeu de clés servi sur ce port local,
# jeton lu par Playwright (frontend-admin/playwright.config.ts).
E2E_ACCESS_DIR="$ROOT/.e2e-access"
E2E_ACCESS_PORT="${E2E_ACCESS_PORT:-8199}"
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
  next_pid=$!  # global : le piège EXIT se déclenche après le retour de la fonction
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
GRANT USAGE ON SCHEMA public TO coges_billing;
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
    # Les parcours y créent chacun leurs comptes : le plafond de l'essai Premium (10) les
    # bloquerait entre eux (ADR 0091). Comme `lift_user_cap` de la suite backend, l'entreprise
    # de parcours passe au palier « sur devis », sans plafond ; le plafond a ses propres tests.
    docker compose exec -T postgres psql -U postgres -d "$E2E_DB" -v ON_ERROR_STOP=1 -q <<'SQL'
INSERT INTO plans (code, name, price_fcfa, max_users, is_orderable)
VALUES ('sur_devis', 'Sur devis', NULL, NULL, false) ON CONFLICT (code) DO NOTHING;
UPDATE subscriptions SET plan_id = (SELECT id FROM plans WHERE code = 'sur_devis')
WHERE company_id = (SELECT id FROM companies WHERE slug = 'e2e');
SQL
    # Administration (ADR 0089) : un compte de l'équipe, et une entreprise que ses parcours
    # suspendent puis réactivent sans toucher aux autres.
    uv run --directory backend python -m app.cli create-platform-user \
      --email "$E2E_ADMIN_EMAIL" --name "Équipe des parcours" --role administrator \
      --password "$E2E_ADMIN_PASSWORD"
    uv run --directory backend python -m app.cli create-company --name "Parcours administration" \
      --slug admin-e2e --manager-email gerant@admin-e2e.example.com \
      --manager-name "Gérant suspendu" --password demo-coges-2026
    # Accès support (ADR 0092) : une entreprise que l'équipe consulte en lecture seule.
    uv run --directory backend python -m app.cli create-company --name "Parcours support" \
      --slug support-e2e --manager-email gerant@support-e2e.example.com \
      --manager-name "Gérant consulté" --password demo-coges-2026
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
    # L'administration exige un jeton Cloudflare Access (ADR 0104), signé par une clé de
    # test dont le jeu public est servi ici ; les routes commerçantes ne changent pas.
    uv run --directory backend python -m tests.helpers.access_tokens "$E2E_ACCESS_DIR"
    python3 -m http.server "$E2E_ACCESS_PORT" --bind 127.0.0.1 \
      --directory "$E2E_ACCESS_DIR" >/dev/null 2>&1 &
    certs_server=$!
    trap 'kill "$certs_server" 2>/dev/null || true' EXIT
    trap 'exit 143' TERM INT
    export COGES_ACCESS_TEAM_DOMAIN=coges-test.cloudflareaccess.com
    export COGES_ACCESS_AUD="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    export COGES_ACCESS_CERTS_URL="http://127.0.0.1:$E2E_ACCESS_PORT/cdn-cgi/access/certs"
    # Pas d'`exec` : le serveur des clés s'arrête avec l'API.
    uv run --directory backend uvicorn app.main:app --port "$E2E_API_PORT"
    ;;
  front)
    # Répertoire de build distinct : le front de développement (:3000, .next) continue de
    # tourner à côté sans conflit.
    run_front .next-e2e "$E2E_API_PORT" "$E2E_FRONT_PORT"
    ;;
  front-prod)
    # Application installable (ADR 0102) : le service worker ne s'enregistre qu'en production.
    # Build à part (.next-pwa), identifiant de build fixe, servi sur :3102.
    cd frontend
    COGES_NEXT_DIST_DIR=.next-pwa NEXT_DEPLOYMENT_ID="${E2E_BUILD_ID:-pwa-e2e-1}" \
      COGES_API_URL="http://localhost:$E2E_API_PORT" ./node_modules/.bin/next build
    exec env COGES_NEXT_DIST_DIR=.next-pwa NEXT_DEPLOYMENT_ID="${E2E_BUILD_ID:-pwa-e2e-1}" \
      COGES_API_URL="http://localhost:$E2E_API_PORT" ./node_modules/.bin/next start --port 3102
    ;;
  admin)
    # « Voir l'entreprise » (accès support, ADR 0092) ouvre le front des parcours.
    export COGES_MERCHANT_URL="http://localhost:$E2E_FRONT_PORT"
    run_front .next-e2e "$E2E_API_PORT" "$E2E_ADMIN_PORT" frontend-admin
    ;;
  system)
    uv run --directory backend python -m tests.e2e.system_state "${2:-}"
    ;;
  *)
    die "usage : $0 reset|api|front|front-prod|admin|system|maquette|maquette-api|maquette-front"
    ;;
esac
