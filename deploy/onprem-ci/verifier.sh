#!/usr/bin/env bash
# Vérification de bout en bout de l'installation sur site (ADR 0124), sur Linux : c'est ce
# que joue le workflow « Sur site », et ce qu'on lance sur un poste de développement.
#
#   deploy/onprem-ci/verifier.sh
#
# Il suit le guide docs/runbooks/sur-site.md, dans le même ordre : réglages, contrôle,
# migrations, démarrage, société, licence (ADR 0125), navigateur ; puis la tâche de nuit à
# +45 jours, redémarrage, changement de version et arrêt brutal de PostgreSQL ; enfin la
# sauvegarde et la restauration (ADR 0127), jouées par le vrai script Windows sous pwsh :
# panne simulée (down -v, réglages neufs), données retrouvées ; enfin le support à distance
# (ADR 0129) : un faux service de pings reçoit les envois, relus par la liste fermée, et un
# diagnostic est fouillé. Il ne touche ni au poste de développement (projet Docker
# « coges-onprem », à part) ni à aucun fichier du dépôt.
#
# Variables :
#   ONPREM_REGISTRY, ONPREM_TAG   images à lancer (défaut : coges-ci/…:ci, construites avant)
#   ONPREM_PORT                   port local (défaut 80)
#   ONPREM_SKIP_BROWSER=1         sans le parcours Chromium
#   ONPREM_KEEP=1                 garder la pile et ses volumes à la fin
#   ONPREM_PWSH                   PowerShell 7 (défaut : pwsh, présent sur les runners GitHub)
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
  # Le faux service de pings du lot 6, s'il tourne.
  if [ -n "${pings_pid:-}" ]; then kill "$pings_pid" 2>/dev/null || true; fi
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

title "Sauvegarde (ADR 0127) : le vrai script Windows, sous pwsh"
pwsh_bin=${ONPREM_PWSH:-pwsh}
command -v "$pwsh_bin" >/dev/null || fail "PowerShell 7 introuvable ($pwsh_bin)"
# Les trois endroits du guide, comme sur le PC : programme, réglages, et C:\CoGes\sauvegardes.
racine="$work/racine"
mkdir -p "$racine" "$work/cles" "$work/usb"
ln -s "$onprem" "$racine/programme"
ln -s "$settings" "$racine/reglages"
coges_ps() { "$pwsh_bin" -NoProfile -File "$onprem/windows/installer.ps1" -Racine "$racine" -NonInteractif -SansNotification "$@"; }
# La paire de clés, tirée « chez le technicien » (commande du guide) : la privée hors du PC.
docker run --rm --network none --user "$(id -u):$(id -g)" -v "$onprem/sauvegarde:/srv/onprem/sauvegarde:ro" \
  -v "$work/cles:/cles" --entrypoint python "$registry/worker:$next_tag" -I \
  /srv/onprem/sauvegarde/coffre.py paire --prive /cles/boutique-test.cle --publique /cles/boutique-test.pub
"$pwsh_bin" -NoProfile -Command ". '$onprem/windows/CoGes.Install.ps1'; \$script:CogesState.NonInteractif = \$true;
  Set-CogesBackupKey -Paths (Get-CogesPath '$racine') -Options @{ ClePublique = '$work/cles/boutique-test.pub' } -Slug '$slug'"
[ -f "$settings/cle-publique-sauvegarde.txt" ] || fail "clé publique non posée"
printf '%s\n' "$slug" > "$work/usb/COGES-SAUVEGARDE.txt"
mkdir -p "$work/cle-sans-repere"

table_counts() {
  dc exec -T postgres psql -U postgres -d coges -XAt -c "
    SELECT 'companies', count(*) FROM companies UNION ALL SELECT 'users', count(*) FROM users
    UNION ALL SELECT 'sales', count(*) FROM sales UNION ALL SELECT 'payments', count(*) FROM payments
    UNION ALL SELECT 'inventory_movements', count(*) FROM inventory_movements
    UNION ALL SELECT 'products', count(*) FROM products UNION ALL SELECT 'subscriptions', count(*) FROM subscriptions
    UNION ALL SELECT 'audit_logs', count(*) FROM audit_logs"
}
before_counts=$(table_counts)
sales_total=$(dc exec -T postgres psql -U postgres -d coges -XAt -c "SELECT count(*) FROM sales WHERE status = 'confirmed'")

# Mémoire de la sauvegarde avec restauration d'essai, pendant que CoGes tourne.
( while :; do docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' 2>/dev/null; sleep 1; done ) > "$work/memoire.txt" &
sampler=$!
start=$SECONDS
COGES_DISQUES_ESSAI="$work/cle-sans-repere:$work/usb" coges_ps -Action Sauvegarder -Essai | tee "$work/sauvegarde.txt"
backup_seconds=$((SECONDS - start))
kill "$sampler" 2>/dev/null || true
wait "$sampler" 2>/dev/null || true
backup=$(find "$racine/sauvegardes" -maxdepth 1 -name 'coges-*.coges' | sort | tail -1)
[ -n "$backup" ] && [ -f "$backup.sha256" ] && [ -f "$backup.manifest.json" ] || fail "sauvegarde absente"
name=$(basename "$backup")
[ -f "$work/usb/CoGes/$name" ] || fail "pas de copie sur le disque préparé"
[ -z "$(ls -A "$work/cle-sans-repere")" ] || fail "un disque sans repère a été écrit"
cmp -s "$backup" "$work/usb/CoGes/$name" || fail "copie hors du PC différente"
grep -q '"dernier_essai_ok": *true' "$racine/sauvegardes/etat.json" || fail "restauration d'essai non réussie"
if head -c 5 "$backup" | grep -q PGDMP; then fail "sauvegarde en clair"; fi
[ -z "$(find "$work" -name '*.dump' 2>/dev/null)" ] || fail "un dump en clair est resté sur le disque"
leftover=$(dc --profile tools run --rm -T --entrypoint sh sauvegarde-pg -c 'ls -A /travail' 2>/dev/null)
[ -z "$leftover" ] || fail "volume de travail non vidé : $leftover"
echo "OK — $name ($(stat -c %s "$backup") o) en ${backup_seconds} s, essai réussi, copie relue, aucun dump en clair."
echo "Mémoire au plus haut pendant la sauvegarde et l'essai :"
LC_ALL=C awk '$1 ~ /^coges-onprem-/ { sub(/-run-[0-9a-f]+$/, "", $1); split($2, a, /[A-Za-z]+/); unit = substr($2, length(a[1]) + 1); v = a[1] + 0;
       if (unit == "GiB") v *= 1024; else if (unit == "KiB") v /= 1024; else if (unit == "B") v /= 1048576;
       if (v > max[$1]) max[$1] = v }
     END { for (n in max) printf "  %-45s %7.1f MiB\n", n, max[n] }' "$work/memoire.txt" | sort

title "La clé privée ne paraît pas dans « docker inspect » (entrée standard seulement)"
secret=$(sed 's/^COGES-CLE-PRIVEE-1://' "$work/cles/boutique-test.cle")
mkfifo "$work/cle.fifo"
dc --profile tools run --rm -T -v "$racine/sauvegardes:/entree:ro" sauvegarde-py coffre.py dechiffrer \
  "/entree/$name" /travail/inspection.dump < "$work/cle.fifo" > "$work/inspection.txt" 2>&1 &
reader=$!
exec 7>"$work/cle.fifo"
for _ in $(seq 1 60); do
  running=$(docker ps -q --filter label=com.docker.compose.project=coges-onprem --filter label=com.docker.compose.service=sauvegarde-py)
  [ -n "$running" ] && break
  sleep 1
done
[ -n "$running" ] || fail "le conteneur de déchiffrement n'a pas démarré"
if docker inspect "$running" | grep -qF -- "$secret"; then fail "la clé privée paraît dans docker inspect"; fi
cat "$work/cles/boutique-test.cle" >&7
exec 7>&-
wait "$reader" || fail "déchiffrement par l'entrée standard : $(cat "$work/inspection.txt")"
dc --profile tools run --rm -T sauvegarde-pg vider >/dev/null
echo "OK — conteneur inspecté pendant qu'il attendait la clé : rien."

title "Panne simulée : down -v, réglages neufs, installation neuve, puis Restaurer"
dc --profile tools down -v --remove-orphans
# Un PC neuf : tous les mots de passe et clés de coges.env changent (le fichier perdu).
python3 - "$env_file" <<'PY'
import base64, re, secrets, sys
path = sys.argv[1]
lines = []
for line in open(path, encoding="utf-8").read().splitlines():
    match = re.fullmatch(r"(COGES_[A-Z_]*(PASSWORD|SECRET))=.*", line)
    if match:
        line = f"{match.group(1)}={secrets.token_hex(32)}"
    elif line.startswith("COGES_MFA_ENCRYPTION_KEY="):
        line = "COGES_MFA_ENCRYPTION_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    lines.append(line)
open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
PY
dc --profile tools config --format json > "$work/rendu-2.json"
python3 "$onprem/check_onprem_env.py" --env-file "$env_file" --rendered "$work/rendu-2.json"
dc --profile tools run --rm migrate > "$work/migrate-neuf.log" 2>&1
dc up -d --wait --wait-timeout 300
# Comme l'installation du lot 3 : la société et sa licence, base vide.
dc --profile tools run --rm -T cli create-company --name "Boutique Test" --slug "$slug" \
  --manager-email "$email" --manager-name "Awa Test" --password "$(python3 -c 'import secrets; print(secrets.token_hex(12))')"
dc --profile tools run --rm -T cli activate-license --slug "$slug" --plan starter >/dev/null
start=$SECONDS
coges_ps -Action Restaurer -Fichier "$work/usb/CoGes/$name" -Cle "$work/cles/boutique-test.cle" -ConfirmerRestauration \
  | tee "$work/restauration.txt"
restore_seconds=$((SECONDS - start))
after_counts=$(table_counts)
[ "$(grep -v '^audit_logs' <<<"$before_counts")" = "$(grep -v '^audit_logs' <<<"$after_counts")" ] \
  || fail "lignes différentes après restauration : $before_counts / $after_counts"
python3 "$ci/controle_donnees.py" --url "$url" --slug "$slug" --email "$email" --min-sales "$sales_total" --exact
license_status "$slug"
expect_line "$work/licence-$slug.txt" "Accès            : actif"
expect_line "$work/licence-$slug.txt" "Fin de période   : sans fin"
expect_line "$work/licence-$slug.txt" "maintenance jusqu'au $maintenance"
old_db=$(dc exec -T postgres psql -U postgres -XAt -c "SELECT datname FROM pg_database WHERE datname LIKE 'coges_avant_%'")
[ -n "$old_db" ] || fail "l'ancienne base n'est pas gardée"
all_healthy
echo "OK — restaurée en ${restore_seconds} s avec des réglages neufs : mêmes lignes, licence revenue, ancienne base gardée ($old_db)."

title "Fichier modifié d'un octet : refusé, rien n'a changé"
mkdir -p "$work/abime"
cp "$work/usb/CoGes/$name"* "$work/abime/"
printf '\x00' | dd of="$work/abime/$name" bs=1 seek=100 conv=notrunc status=none
if coges_ps -Action Restaurer -Fichier "$work/abime/$name" -Cle "$work/cles/boutique-test.cle" -ConfirmerRestauration > "$work/abime.txt"; then
  fail "un fichier abîmé a été restauré"
fi
grep -q 'sha256' "$work/abime.txt" || fail "message du refus : $(cat "$work/abime.txt")"
python3 "$ci/controle_donnees.py" --url "$url" --slug "$slug" --email "$email" --min-sales "$sales_total" --exact
echo "OK — refusé à l'empreinte."

title "Sauvegarde d'une révision inconnue du programme : refusée"
mkdir -p "$work/future"
cp "$work/usb/CoGes/$name"* "$work/future/"
python3 - "$work/future/$name.manifest.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
data["alembic_revision"], data["coges_version"] = "9999", "v9.9.9"
json.dump(data, open(sys.argv[1], "w", encoding="utf-8"))
PY
if coges_ps -Action Restaurer -Fichier "$work/future/$name" -Cle "$work/cles/boutique-test.cle" -ConfirmerRestauration > "$work/future.txt"; then
  fail "une sauvegarde plus récente que le programme a été restaurée"
fi
grep -q "Installez d'abord la version v9.9.9" "$work/future.txt" || fail "message du refus : $(cat "$work/future.txt")"
echo "OK — « installez d'abord la version v9.9.9 »."

title "Échec après la bascule (simulé) : retour automatique à l'ancienne base"
if COGES_ESSAI_ECHEC_APRES_BASCULE=1 coges_ps -Action Restaurer -Fichier "$work/usb/CoGes/$name" \
    -Cle "$work/cles/boutique-test.cle" -ConfirmerRestauration > "$work/retour.txt"; then
  fail "l'échec simulé n'a pas été vu"
fi
grep -q "ancienne base est remise en place" "$work/retour.txt" || fail "message du retour : $(cat "$work/retour.txt")"
wait_for_code "$url/api/v1/health/ready" 200 90
python3 "$ci/controle_donnees.py" --url "$url" --slug "$slug" --email "$email" --min-sales "$sales_total" --exact
all_healthy
echo "OK — base d'avant remise, CoGes répond."

title "État, puis nettoyage des anciennes bases (code de la boutique)"
coges_ps -Action Etat -CodeBoutique "$slug" | tee "$work/etat.txt"
grep -q "Ancienne base gardée" "$work/etat.txt" || fail "Etat ne signale pas l'ancienne base"
grep -q "Dernière sauvegarde : " "$work/etat.txt" || fail "Etat ne dit pas la dernière sauvegarde"
coges_ps -Action NettoyerAncienneBase -CodeBoutique "$slug"
left=$(dc exec -T postgres psql -U postgres -XAt -c "SELECT count(*) FROM pg_database WHERE datname ~ '^coges_(avant|echec)_'")
[ "$left" = 0 ] || fail "$left ancienne(s) base(s) restante(s)"
[ -z "$(find "$racine/journaux" -type f -exec grep -lF -- "$secret" {} +)" ] || fail "la clé privée est dans un journal"
echo "OK — anciennes bases supprimées ; sauvegarde ${backup_seconds} s, restauration ${restore_seconds} s."

title "Support à distance (ADR 0129) : un faux service de pings, à la place de Healthchecks.io"
pings="$work/pings"
pings_port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
python3 "$ci/controle_remontee.py" serveur --port "$pings_port" --dossier "$pings" 2>"$work/pings.log" &
pings_pid=$!
pings_url="http://127.0.0.1:$pings_port/ping"
for _ in $(seq 1 20); do
  curl -s -o /dev/null -X POST "$pings_url/essai-de-depart" && break
  sleep 0.5
done
rm -f "$pings"/*.txt
# Le fichier préparé chez CoGes (guide) : trois adresses, le numéro affiché par « Aide CoGes ».
python3 - "$work/support.json" "$pings_url" <<'PY2'
import json, secrets, sys
base = sys.argv[2]
json.dump({"adresses": {s: f"{base}/{s}-{secrets.token_hex(12)}" for s in ("vie", "sauvegarde", "mise-a-jour")},
           "telephone_coges": "+221 00 000 00 00"}, open(sys.argv[1], "w", encoding="utf-8"))
PY2
coges_ps -Action ConfigurerSupport -Support "$work/support.json"
grep -q '"remontee": *true' "$settings/support.json" || fail "remontée non activée"
coges_ps -Action TesterSupport | tee "$work/tester-support.txt"
[ "$(grep -c 'reçu par CoGes' "$work/tester-support.txt")" = 3 ] || fail "TesterSupport : les trois adresses n'ont pas répondu"

title "Sauvegarde réussie ⇒ « sauvegarde » ; ratée exprès (clé publique retirée) ⇒ /fail avec la raison"
coges_ps -Action Sauvegarder > "$work/sauvegarde-support.txt"
mv "$settings/cle-publique-sauvegarde.txt" "$work/cle-publique-ecartee.txt"
if coges_ps -Action Sauvegarder > "$work/sauvegarde-ratee.txt"; then fail "la sauvegarde sans clé a réussi"; fi
mv "$work/cle-publique-ecartee.txt" "$settings/cle-publique-sauvegarde.txt"
# L'ouverture de session (tâche « CoGes - démarrage ») : up -d sur la pile déjà lancée, puis « vie ».
"$pwsh_bin" -NoProfile -File "$onprem/windows/demarrage.ps1" -Racine "$racine"
python3 "$ci/controle_remontee.py" corps "$pings" --attendu sauvegarde:aucune --attendu sauvegarde-fail:cle-absente --attendu vie:aucune
echo "Corps reçu pour l'échec (tout ce qui sort du PC) :"
cat "$(find "$pings" -name '*-sauvegarde-fail.txt' | sort | tail -1)"
for file in "$pings"/*.txt; do
  if grep -qF -e "$slug" -e "Boutique Test" -e "$email" "$file"; then fail "$(basename "$file") nomme la boutique"; fi
done
coges_ps -Action Etat -CodeBoutique "$slug" > "$work/etat-support.txt"
grep -q "Remontée vers CoGes : active (3 adresse(s)), dernier envoi le" "$work/etat-support.txt" || fail "Etat ne dit pas la remontée"
if grep -qF "$pings_url" "$work/etat-support.txt"; then fail "Etat montre une adresse de ping"; fi
if grep -rqF "$pings_url" "$racine/journaux"; then fail "une adresse de ping est dans un journal"; fi
echo "OK — test, sauvegarde, /fail cle-absente, vie : reçus et dans la liste ; aucune adresse au journal ni dans Etat."

title "Diagnostic : zip sur le Bureau, fouillé (aucun secret du coges.env du job, aucun nom de la démo)"
mkdir -p "$work/bureau"
COGES_BUREAU_ESSAI="$work/bureau" coges_ps -Action Diagnostic | tee "$work/diagnostic.txt"
zip=$(find "$work/bureau" -name 'CoGes-diagnostic-*.zip' | head -1)
[ -n "$zip" ] || fail "aucun diagnostic sur le Bureau"
mapfile -t demo_names < <(dc exec -T postgres psql -U postgres -d coges -XAt -c "
  SELECT name FROM companies UNION SELECT name FROM products UNION SELECT name FROM customers
  UNION SELECT full_name FROM users WHERE full_name IS NOT NULL" | awk 'length($0) >= 4')
[ "${#demo_names[@]}" -gt 0 ] || fail "aucun nom de la démo à chercher"
forbidden=()
for name in "${demo_names[@]}" "$email" "$pings_url"; do forbidden+=(--interdit "$name"); done
python3 "$ci/controle_remontee.py" zip "$zip" --env "$env_file" "${forbidden[@]}"
echo "OK — ${#demo_names[@]} nom(s) de la démo cherchés : absents."

title "Vérification sur site réussie"
