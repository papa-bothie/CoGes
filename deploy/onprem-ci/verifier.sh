#!/usr/bin/env bash
# Vérification de bout en bout de l'installation sur site (ADR 0124), sur Linux : c'est ce
# que joue le workflow « Sur site », et ce qu'on lance sur un poste de développement.
#
#   deploy/onprem-ci/verifier.sh
#
# Il suit le guide docs/runbooks/sur-site.md, dans le même ordre : réglages, contrôle,
# migrations, démarrage, société, licence (ADR 0125), navigateur ; puis la tâche de nuit à
# +45 jours, redémarrage, changement de version et arrêt brutal de PostgreSQL. Il ne touche ni au poste de développement (projet Docker
# « coges-onprem », à part) ni à aucun fichier du dépôt.
#
# Variables :
#   ONPREM_REGISTRY, ONPREM_TAG   images à lancer (défaut : coges-ci/…:ci, construites avant)
#   ONPREM_PORT                   port local (défaut 80)
#   ONPREM_SKIP_BROWSER=1         sans le parcours Chromium
#   ONPREM_KEEP=1                 garder la pile et ses volumes à la fin
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
onprem="$root/deploy/onprem"
ci="$root/deploy/onprem-ci"
registry=${ONPREM_REGISTRY:-coges-ci}
tag=${ONPREM_TAG:-ci}
next_tag="$tag-suivante"
port=${ONPREM_PORT:-80}
if [ "$port" = 80 ]; then url=http://localhost; else url="http://localhost:$port"; fi

slug=boutique-test
email=gerant@boutique.example
# Société témoin, jamais licenciée : la tâche de nuit doit la suspendre (ADR 0125).
witness=boutique-temoin
witness_email=gerant@temoin.example
ONPREM_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(12))')
export ONPREM_PASSWORD

# Les réglages du client vivent HORS du dossier du programme (les trois endroits).
work=$(mktemp -d)
settings="$work/reglages"
mkdir -p "$settings"
env_file="$settings/coges.env"

dc() { docker compose --env-file "$env_file" -f "$onprem/docker-compose.yml" "$@"; }
title() { printf '\n=== %s ===\n' "$*"; }
fail() { printf 'ÉCHEC — %s\n' "$*" >&2; exit 1; }

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    title "État au moment de l'échec"
    dc ps -a || true
    dc logs --tail 40 api worker relay beat caddy postgres 2>&1 | tail -150 || true
  fi
  if [ "${ONPREM_KEEP:-}" != 1 ]; then
    dc --profile tools down -v --remove-orphans >/dev/null 2>&1 || true
    docker image rm "$registry/front:$next_tag" "$registry/api:$next_tag" \
      "$registry/worker:$next_tag" >/dev/null 2>&1 || true
    rm -rf "$work"
  else
    echo "Pile gardée. Réglages : $env_file"
  fi
  exit "$status"
}
trap cleanup EXIT

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1" || true; }

wait_for_code() { # adresse, code attendu, délai en secondes
  local deadline=$((SECONDS + $3)) code=
  while [ "$SECONDS" -lt "$deadline" ]; do
    code=$(http_code "$1")
    [ "$code" = "$2" ] && return 0
    sleep 3
  done
  fail "$1 répond $code, $2 attendu"
}

all_healthy() {
  # Tout conteneur tourne ; celui qui a une sonde est « healthy ».
  local bad
  bad=$(dc ps -a --format '{{.Service}} {{.State}} {{.Health}}' \
    | awk '$2 != "running" || ($3 != "" && $3 != "healthy")')
  [ -z "$bad" ] || fail "conteneurs en mauvais état : $bad"
}

data_are_there() {
  python3 "$ci/controle_donnees.py" --url "$url" --slug "$slug" --email "$email" --min-sales "$1"
}

# ------------------------------------------------------------------------------------
title "Réglages : modèle rempli, hors du dossier du programme"
python3 - "$onprem/coges.env.example" "$env_file" "$registry" "$tag" "$port" "$url" <<'PY'
import base64, re, secrets, sys

model, target, registry, tag, port, url = sys.argv[1:]
values = {
    "COGES_IMAGE_TAG": tag,
    "COGES_IMAGE_REGISTRY": registry,
    "COGES_HTTP_PORT": port,
    "COGES_PUBLIC_URL": url,
    "COGES_MFA_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
}
lines = []
for line in open(model, encoding="utf-8").read().splitlines():
    match = re.fullmatch(r"([A-Z_]+)=(.*)", line)
    if match:
        key = match.group(1)
        line = f"{key}={values.get(key) or match.group(2) or secrets.token_hex(32)}"
    lines.append(line)
open(target, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
PY

title "Contrôle des réglages (fichier, puis compose rendu)"
dc --profile tools config --quiet
dc --profile tools config --format json > "$work/rendu.json"
python3 "$onprem/check_onprem_env.py" --env-file "$env_file" --rendered "$work/rendu.json"
# Comme sur le PC du client, qui n'a pas Python : dans l'image worker, sans réseau.
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$onprem:/onprem:ro" -v "$settings:/reglages:ro" \
  --entrypoint python "$registry/worker:$tag" \
  /onprem/check_onprem_env.py --env-file /reglages/coges.env

title "Migrations (service ponctuel migrate, seul à recevoir le DSN propriétaire)"
dc --profile tools run --rm migrate 2>&1 | tee "$work/migrate-1.log" | tail -3
grep -q "Running upgrade" "$work/migrate-1.log" || fail "la première migration n'a rien joué"

title "Rejouer migrate ne change rien"
dc --profile tools run --rm migrate > "$work/migrate-2.log" 2>&1
if grep -q "Running upgrade" "$work/migrate-2.log"; then
  fail "la seconde migration a rejoué des révisions"
fi
echo "OK — aucune révision rejouée."

title "Démarrage"
dc up -d --wait --wait-timeout 300
all_healthy

title "Société (service ponctuel cli)"
dc --profile tools run --rm -T cli create-company --name "Boutique Test" --slug "$slug" \
  --manager-email "$email" --manager-name "Awa Test" --password "$ONPREM_PASSWORD"

license_status() { # identifiant → fichier de sortie
  dc --profile tools run --rm -T cli license-status --slug "$1" | tee "$work/licence-$1.txt"
}
expect_line() { # fichier, ligne attendue
  grep -qF -- "$2" "$1" || fail "« $2 » absent de $(basename "$1")"
}

title "Licence (service ponctuel cli) : abonnement actif, sans fin"
contract=$(date -u +%d/%m/%Y)
maintenance=$(date -u -d '+1 year' +%d/%m/%Y)
dc --profile tools run --rm -T cli activate-license --slug "$slug" --plan business \
  --note "Contrat du $contract, maintenance jusqu'au $maintenance" | tee "$work/activation.txt"
expect_line "$work/activation.txt" "Licence activée."
again=$(dc --profile tools run --rm -T cli activate-license --slug "$slug" --plan business)
grep -qF "rien à faire" <<<"$again" || fail "la licence rejouée a encore écrit : $again"
license_status "$slug"
expect_line "$work/licence-$slug.txt" "Accès            : actif"
expect_line "$work/licence-$slug.txt" "Fin de période   : sans fin"
expect_line "$work/licence-$slug.txt" "maintenance jusqu'au $maintenance"
if dc --profile tools run --rm -T cli activate-license --slug inconnue --plan business \
    >/dev/null 2>&1; then
  fail "une licence est acceptée pour une société inconnue"
fi

title "Société témoin, sans licence"
dc --profile tools run --rm -T cli create-company --name "Boutique Temoin" --slug "$witness" \
  --manager-email "$witness_email" --manager-name "Témoin" --password "$ONPREM_PASSWORD"

title "Ce que voit le PC : $url"
wait_for_code "$url/" 200 60
wait_for_code "$url/api/v1/health" 200 30
wait_for_code "$url/api/v1/health/ready" 200 30
wait_for_code "$url/api/v1/platform/" 404 10
wait_for_code "$url/api/v1/platform/auth/login" 404 10
# Documentation de l'API fermée (COGES_ENV=production).
wait_for_code "$url/api/v1/docs" 404 10
headers=$(curl -sI --max-time 10 "$url/api/v1/health")
if grep -qi '^strict-transport-security' <<<"$headers"; then
  fail "un en-tête HSTS est servi en HTTP"
fi
grep -qi '^x-content-type-options: nosniff' <<<"$headers" || fail "en-têtes de sécurité absents"
echo "OK — site, API, administration en 404, pas de HSTS."

title "Un seul port publié, sur la boucle locale"
published=$(docker ps --filter "label=com.docker.compose.project=coges-onprem" --format '{{.Ports}}' \
  | tr ',' '\n' | grep -- '->' | sed 's/^ *//' | sort -u)
echo "$published"
[ "$published" = "127.0.0.1:$port->80/tcp" ] || fail "ports publiés inattendus"

title "Aucune sortie depuis les conteneurs"
for service in api worker front; do
  if dc exec -T "$service" sh -c 'command -v python >/dev/null \
      && python -c "import socket; socket.create_connection((\"1.1.1.1\", 443), 5)" \
      || node -e "require(\"net\").connect({host:\"1.1.1.1\",port:443,timeout:5000}).on(\"connect\",()=>process.exit(0)).on(\"error\",()=>process.exit(1)).on(\"timeout\",()=>process.exit(1))"' \
      >/dev/null 2>&1; then
    fail "le service $service joint Internet"
  fi
done
echo "OK — api, worker et front ne joignent pas Internet."

if [ "${ONPREM_SKIP_BROWSER:-}" != 1 ]; then
  title "Parcours Chromium : connexion, rechargement, service worker, vente"
  ONPREM_URL="$url" ONPREM_SLUG="$slug" ONPREM_EMAIL="$email" \
    ONPREM_SCREENSHOT="${ONPREM_SCREENSHOT:-$work/echec.png}" node "$ci/parcours.mjs"
  sales=1
else
  sales=0
fi
data_are_there "$sales"

title "Mémoire pendant l'usage (plafond de chaque conteneur à droite)"
# shellcheck disable=SC2046
docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}' $(dc ps -q) | sort

title "Tâches planifiées déclenchées à la main : aucun bruit dû aux réglages vides"
tasks=$(dc exec -T worker python -c "
from app.workers.beat import BEAT_SCHEDULE
print(' '.join(sorted({entry['task'] for entry in BEAT_SCHEDULE.values()})))")
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
count=0
for task in $tasks; do
  dc exec -T worker celery -A app.workers.celery_app call "$task" >/dev/null
  count=$((count + 1))
done
# La file se vide : plus rien en attente ni en cours.
deadline=$((SECONDS + 180))
while [ "$SECONDS" -lt "$deadline" ]; do
  sleep 5
  waiting=$(dc exec -T redis redis-cli llen celery | tr -d '\r')
  active=$(dc exec -T worker celery -A app.workers.celery_app inspect active --json 2>/dev/null \
    | python3 -c 'import json,sys; print(sum(len(v) for v in json.loads(sys.stdin.read() or "{}").values()))' \
    || echo 1)
  [ "$waiting" = 0 ] && [ "$active" = 0 ] && break
done
[ "$waiting" = 0 ] && [ "$active" = 0 ] || fail "la file ne s'est pas vidée ($waiting en attente, $active en cours)"
sleep 3
noise=$(dc logs --no-log-prefix --since "$since" worker beat relay 2>&1 \
  | grep -E 'ERROR|CRITICAL|Traceback|WARNING' || true)
[ -z "$noise" ] || fail "journaux de worker, beat ou relay : $noise"
done_tasks=$(dc logs --no-log-prefix --since "$since" worker 2>&1 | grep -c 'succeeded' || true)
[ "$done_tasks" -ge "$count" ] || fail "$done_tasks tâche(s) réussie(s) pour $count déclenchée(s)"
echo "OK — $count tâches déclenchées, $done_tasks exécutions réussies, journaux propres."

title "Tâche de nuit des abonnements à +45 jours : seule la société sans licence est suspendue"
# Dans le conteneur worker, qui tient le DSN de la plateforme ; la tâche est appelée
# directement (synchrone), avec la date de son paramètre `now`.
later=$(date -u -d '+45 days' +%Y-%m-%dT%H:%M:%S+00:00)
dc exec -T worker python -c '
import sys
from app.workers.tasks.platform import subscriptions_daily
print(f"{subscriptions_daily(sys.argv[1])} avis : essais finis ou proches de leur fin")' "$later"
data_are_there "$sales"  # la société licenciée se connecte toujours
license_status "$slug"
expect_line "$work/licence-$slug.txt" "Accès            : actif"
license_status "$witness"
expect_line "$work/licence-$witness.txt" "Accès            : suspendu"
refused=$(curl -s --max-time 10 -H 'Content-Type: application/json' \
  -d "{\"company_slug\":\"$witness\",\"email\":\"$witness_email\",\"password\":\"$ONPREM_PASSWORD\"}" \
  -w ' %{http_code}' "$url/api/v1/auth/login")
grep -q 'company_suspended.* 403$' <<<"$refused" || fail "connexion du témoin : $refused"
echo "OK — licenciée acceptée, témoin refusé (403 company_suspended)."

title "Arrêt puis redémarrage (down, up, sans -v) : les données sont là"
dc down
dc up -d --wait --wait-timeout 300
wait_for_code "$url/api/v1/health/ready" 200 60
data_are_there "$sales"

title "Mise à jour à la main (guide) : nouvelle étiquette, pull, arrêt, migrate, up"
for image in front api worker; do
  docker tag "$registry/$image:$tag" "$registry/$image:$next_tag"
done
before=$(dc ps -q api)
sed -i "s|^COGES_IMAGE_TAG=.*|COGES_IMAGE_TAG=$next_tag|" "$env_file"
# Les images de CoGes de ce test sont locales ; celles du registre public se tirent
# (trois essais : une coupure passagère du registre n'est pas un échec du sur site).
pulled=0
for attempt in 1 2 3; do
  if dc pull --quiet postgres redis caddy; then pulled=1; break; fi
  echo "pull : essai $attempt manqué, nouvel essai dans 10 s"
  sleep 10
done
[ "$pulled" = 1 ] || fail "le registre public ne répond pas (docker compose pull)"
dc stop api worker beat relay front
dc --profile tools run --rm migrate > "$work/migrate-3.log" 2>&1
dc up -d --wait --wait-timeout 300
all_healthy
[ "$(dc ps -q api)" != "$before" ] || fail "le conteneur de l'API n'a pas été recréé"
running=$(docker inspect -f '{{.Config.Image}}' "$(dc ps -q api)")
[ "$running" = "$registry/api:$next_tag" ] || fail "version en cours : $running"
echo "Version en cours : $running"
wait_for_code "$url/api/v1/health/ready" 200 60
data_are_there "$sales"

title "Arrêt brutal de PostgreSQL en pleine marche : retour seul à l'état sain"
# SIGQUIT au postmaster : arrêt immédiat, sans point de contrôle, comme une panne. Docker
# relance le conteneur (restart: unless-stopped), PostgreSQL rejoue son journal.
restarts=$(docker inspect -f '{{.RestartCount}}' "$(dc ps -q postgres)")
dc exec -T postgres sh -c 'kill -QUIT 1'
deadline=$((SECONDS + 120))
while [ "$SECONDS" -lt "$deadline" ]; do
  sleep 3
  state=$(docker inspect -f '{{.RestartCount}} {{.State.Health.Status}}' "$(dc ps -aq postgres)")
  [ "$state" = "$((restarts + 1)) healthy" ] && break
done
[ "$state" = "$((restarts + 1)) healthy" ] || fail "PostgreSQL n'est pas revenu seul ($state)"
wait_for_code "$url/api/v1/health/ready" 200 90
data_are_there "$sales"

title "docker kill de PostgreSQL : un arrêt « à la main » pour Docker, relancé par up"
# Docker ne relance jamais un conteneur arrêté par `docker kill` ou `docker stop`, quelle
# que soit la politique de redémarrage : c'est `up -d` qui le ramène (guide).
docker kill "$(dc ps -q postgres)" >/dev/null
sleep 5
dc up -d --wait --wait-timeout 300
wait_for_code "$url/api/v1/health/ready" 200 90
data_are_there "$sales"
all_healthy

title "Vérification sur site réussie"
