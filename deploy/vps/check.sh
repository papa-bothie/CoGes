#!/usr/bin/env bash
# Bilan du VPS CoGes en une commande (ADR 0083, docs/runbooks/vps.md).
#
#   /opt/coges/check.sh                 # production
#   /opt/coges/check.sh preprod         # préproduction (si elle tourne)
#
# Disque, mémoire, swap, conteneurs et leur santé, expiration du certificat, mises à jour
# en attente, bannissements fail2ban, latence vers Neon, réponse de /api/v1/health/ready.
# Code de sortie 1 si un point est rouge. Lecture seule : ne change rien.

set -uo pipefail

STACK=${1:-production}
COGES_ETC=${COGES_ETC:-/etc/coges}
case "$STACK" in
  production) PROJECT=coges ENV_FILE="$COGES_ETC/coges.env" ;;
  preprod) PROJECT=coges-preprod ENV_FILE="$COGES_ETC/preprod.env" ;;
  *)
    echo "usage : check.sh [production|preprod]" >&2
    exit 2
    ;;
esac

RED=0
ok() { printf '  OK     %s\n' "$*"; }
warn() { printf '  ATTENTION %s\n' "$*"; }
bad() {
  printf '  ROUGE  %s\n' "$*"
  RED=1
}

env_value() { sed -n "s/^$1=//p" "$ENV_FILE" 2>/dev/null | tail -n 1; }

echo "CoGes — bilan de $(hostname) ($STACK), $(date -u '+%d/%m/%Y %H:%M') UTC"

echo "Disque"
used=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if ((used >= 90)); then bad "/ plein à $used %"; elif ((used >= 80)); then warn "/ à $used %"; else ok "/ à $used %"; fi
docker_used=$(docker system df --format '{{.Type}} {{.Size}}' 2>/dev/null | tr '\n' ' ')
[[ -n "$docker_used" ]] && ok "Docker : $docker_used"

echo "Mémoire"
read -r _ total used_mem _ _ _ available < <(free -m | awk '/^Mem:/')
ok "RAM : $used_mem Mo utilisés sur $total, $available disponibles"
((available < 300)) && bad "moins de 300 Mo disponibles"
read -r _ swap_total swap_used _ < <(free -m | awk '/^Swap:/')
if ((swap_total == 0)); then bad "aucun swap"; elif ((swap_used * 2 > swap_total)); then warn "swap à $swap_used/$swap_total Mo"; else ok "swap : $swap_used/$swap_total Mo"; fi

echo "Conteneurs ($PROJECT)"
if ! docker compose -p "$PROJECT" ps >/dev/null 2>&1; then
  bad "docker compose injoignable"
else
  while IFS=$'\t' read -r service state health; do
    case "$health" in
      healthy | "")
        if [[ "$state" == running ]]; then ok "$service : $state ${health}"; else bad "$service : $state"; fi
        ;;
      *) bad "$service : $state, $health" ;;
    esac
  done < <(docker compose -p "$PROJECT" ps --all --format '{{.Service}}\t{{.State}}\t{{.Health}}')
  restarts=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" -q \
    | xargs -r docker inspect --format '{{.Name}} {{.RestartCount}}' | awk '$2 > 3')
  [[ -n "$restarts" ]] && warn "redémarrages répétés : $restarts"
fi

DOMAIN=$(env_value COGES_DOMAIN)
[[ "$STACK" == preprod ]] && DOMAIN="preprod.$DOMAIN"

echo "Certificat"
if [[ -n "$DOMAIN" ]]; then
  expiry=$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$DOMAIN" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
  if [[ -z "$expiry" ]]; then
    bad "aucun certificat servi pour $DOMAIN"
  else
    days=$((($(date -d "$expiry" +%s) - $(date +%s)) / 86400))
    if ((days < 7)); then bad "$DOMAIN expire dans $days jours"; elif ((days < 20)); then warn "$DOMAIN expire dans $days jours (Caddy renouvelle à 30 j)"; else ok "$DOMAIN valable encore $days jours"; fi
  fi
else
  bad "COGES_DOMAIN illisible dans $ENV_FILE"
fi

echo "Mises à jour"
pending=$(apt list --upgradable 2>/dev/null | grep -c security || true)
if ((pending > 0)); then warn "$pending mises à jour de sécurité en attente"; else ok "aucune mise à jour de sécurité en attente"; fi
[[ -f /var/run/reboot-required ]] && warn "redémarrage demandé (fait automatiquement à 05 h 15 UTC)"

echo "fail2ban"
if command -v fail2ban-client >/dev/null 2>&1; then
  banned=$(fail2ban-client status sshd 2>/dev/null | awk -F: '/Currently banned/ {gsub(/ /,"",$2); print $2}')
  total_banned=$(fail2ban-client status sshd 2>/dev/null | awk -F: '/Total banned/ {gsub(/ /,"",$2); print $2}')
  ok "SSH : ${banned:-?} adresses bannies en ce moment, ${total_banned:-?} depuis le démarrage"
else
  warn "fail2ban absent"
fi

echo "Neon"
dsn=$(env_value COGES_DATABASE_URL_APP)
neon_host=$(sed -E 's#^[^@]*@([^/:?]+).*#\1#' <<<"$dsn")
if [[ -n "$neon_host" && "$neon_host" != "$dsn" ]]; then
  latency=$(curl -s -o /dev/null --max-time 5 -w '%{time_connect}' "telnet://$neon_host:5432" </dev/null 2>/dev/null || true)
  if [[ -n "$latency" && "$latency" != 0.000000 ]]; then
    ok "connexion TCP à $neon_host : $(awk -v t="$latency" 'BEGIN { printf "%.0f", t * 1000 }') ms"
  else
    bad "Neon injoignable ($neon_host:5432)"
  fi
else
  bad "COGES_DATABASE_URL_APP illisible"
fi

echo "Application"
if [[ -n "$DOMAIN" ]]; then
  body=$(curl -s --max-time 10 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/v1/health/ready")
  if grep -q '"status":"ok"' <<<"$body"; then ok "health/ready : $body"; else bad "health/ready : ${body:-aucune réponse}"; fi
fi

if ((RED)); then
  echo "Bilan : ROUGE — voir docs/runbooks/vps.md"
  exit 1
fi
echo "Bilan : tout est vert"
