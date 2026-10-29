#!/usr/bin/env bash
# Déploiement d'une version de CoGes sur le VPS (ADR 0083).
#
#   deploy.sh <production|preprod> <vX.Y.Z|sha>   déployer cette version
#   deploy.sh <production|preprod> rollback        revenir à la version précédente
#   deploy.sh <production|preprod> status          version courante et santé
#   deploy.sh preprod stop                         arrêter la préproduction
#
# Installé par bootstrap.sh dans /opt/coges/deploy.sh (propriété de root, non modifiable
# par `deploy`). La clé SSH de GitHub Actions est bridée dans authorized_keys par
#   command="/opt/coges/deploy.sh",no-port-forwarding,no-pty,…
# Elle ne peut donc lancer que ce script : ses arguments arrivent par
# SSH_ORIGINAL_COMMAND et sont validés ici, mot par mot.
#
# Étapes : verrou, contrôle du fichier de secrets (aucun DSN propriétaire), connexion à
# ghcr.io en lecture seule, récupération du « bundle » (compose et Caddyfile de CETTE
# version), pull, `docker compose up -d`, vérification par Caddy (/api/v1/health/ready
# puis /login), retour automatique à la version précédente si la vérification échoue.
# Journal : /var/log/coges/deploy.log.

set -euo pipefail

COGES_ROOT=${COGES_ROOT:-/opt/coges}
COGES_ETC=${COGES_ETC:-/etc/coges}
COGES_LOG_DIR=${COGES_LOG_DIR:-/var/log/coges}
# Essais locaux seulement : port HTTPS de Caddy et certificat interne (ADR 0083, § essai).
COGES_HTTPS_PORT=${COGES_HTTPS_PORT:-443}
COGES_DEPLOY_INSECURE=${COGES_DEPLOY_INSECURE:-0}
# Délai laissé à la nouvelle version pour répondre, en secondes.
COGES_DEPLOY_WAIT=${COGES_DEPLOY_WAIT:-180}
REGISTRY_DEFAULT=ghcr.io/papa-bothie/coges

STATE_DIR="$COGES_ROOT/state"
RELEASES_DIR="$COGES_ROOT/releases"
LOG_FILE="$COGES_LOG_DIR/deploy.log"

log() {
  local line
  line="$(date -u +%Y-%m-%dT%H:%M:%SZ) ${STACK:-?} $*"
  echo "$line"
  if [[ -w "$COGES_LOG_DIR" ]]; then
    echo "$line" >>"$LOG_FILE"
  fi
}

die() {
  log "ÉCHEC : $*"
  exit 1
}

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

# --- Arguments : ligne de commande, ou SSH_ORIGINAL_COMMAND sous la clé bridée --------
if [[ $# -eq 0 && -n "${SSH_ORIGINAL_COMMAND:-}" ]]; then
  # Découpage sur les espaces seulement : aucun développement du shell sur ce texte.
  read -r -a ARGS <<<"$SSH_ORIGINAL_COMMAND"
  # « deploy.sh production v1.2.3 » ou « production v1.2.3 » : le nom du script est toléré.
  if [[ ${#ARGS[@]} -gt 0 && "${ARGS[0]##*/}" == "deploy.sh" ]]; then
    ARGS=("${ARGS[@]:1}")
  fi
else
  ARGS=("$@")
fi
[[ ${#ARGS[@]} -eq 2 ]] || usage
STACK=${ARGS[0]}
ACTION=${ARGS[1]}

case "$STACK" in
  production) PROJECT=coges ENV_FILE="$COGES_ETC/coges.env" PROFILE=(--profile edge) ;;
  preprod) PROJECT=coges-preprod ENV_FILE="$COGES_ETC/preprod.env" PROFILE=() ;;
  *) die "pile inconnue « $STACK » (production ou preprod)" ;;
esac

VERSION_RE='^(v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?|[0-9a-f]{7,40})$'
case "$ACTION" in
  rollback | status) ;;
  stop) [[ "$STACK" == preprod ]] || die "seule la préproduction s'arrête par ce script" ;;
  *) [[ "$ACTION" =~ $VERSION_RE ]] || die "version refusée « $ACTION » (vX.Y.Z ou SHA)" ;;
esac

[[ -r "$ENV_FILE" ]] || die "fichier de secrets illisible : $ENV_FILE"

env_value() {
  # Lit une variable du fichier de secrets sans l'exécuter (aucun `source`).
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1
}

# La pile démarrée est celle de la ligne de commande, jamais celle d'un fichier copié :
# une préproduction prise du modèle de production prendrait ses alias réseau sur
# `coges_edge` (ADR 0088). Exportée, elle prime sur le fichier de secrets dans compose.
declared_stack=$(env_value COGES_STACK)
if [[ -n "$declared_stack" && "$declared_stack" != "$STACK" ]]; then
  die "COGES_STACK vaut « $declared_stack » dans $ENV_FILE pour la pile « $STACK »"
fi
export COGES_STACK="$STACK"

DOMAIN=$(env_value COGES_DOMAIN)
[[ -n "$DOMAIN" ]] || die "COGES_DOMAIN vide dans $ENV_FILE"
[[ "$STACK" == preprod ]] && DOMAIN="preprod.$DOMAIN"
REGISTRY=$(env_value COGES_IMAGE_REGISTRY)
REGISTRY=${REGISTRY:-$REGISTRY_DEFAULT}

# Porte de l'administration (ADR 0104) : en mode `cloudflare`, le conteneur cloudflared
# (profil `tunnel`) démarre avec la pile de production. Les guillemets sont tolérés.
ADMIN_GATE=$(env_value COGES_ADMIN_GATE | tr -d "\"'")
TUNNEL=0
if [[ "$STACK" == production && "$ADMIN_GATE" == cloudflare ]]; then
  TUNNEL=1
  PROFILE+=(--profile tunnel)
fi

mkdir -p "$STATE_DIR" "$RELEASES_DIR"
CURRENT_FILE="$STATE_DIR/$STACK.version"
PREVIOUS_FILE="$STATE_DIR/$STACK.previous"

# Un seul déploiement à la fois sur la machine, toutes piles confondues.
exec 9>"$STATE_DIR/deploy.lock"
flock -w 600 9 || die "un autre déploiement tient le verrou depuis 10 min"

compose() {
  local version=$1
  shift
  COGES_IMAGE_TAG="$version" docker compose \
    -p "$PROJECT" \
    -f "$RELEASES_DIR/$version/docker-compose.yml" \
    --env-file "$ENV_FILE" \
    "${PROFILE[@]}" "$@"
}

registry_login() {
  # Jeton GitHub en LECTURE SEULE des paquets, déposé par le propriétaire.
  local token_file="$COGES_ETC/ghcr-token" user_file="$COGES_ETC/ghcr-user"
  if [[ -r "$token_file" && -r "$user_file" ]]; then
    docker login ghcr.io --username "$(cat "$user_file")" --password-stdin \
      <"$token_file" >/dev/null
  fi
}

fetch_bundle() {
  # Le compose et le Caddyfile de CETTE version, tirés de l'image `bundle` : revenir en
  # arrière ramène aussi la configuration qui allait avec.
  local version=$1 target="$RELEASES_DIR/$1" container
  if [[ -f "$target/docker-compose.yml" ]]; then
    return
  fi
  docker image inspect "$REGISTRY/bundle:$version" >/dev/null 2>&1 \
    || docker pull --quiet "$REGISTRY/bundle:$version" >/dev/null
  container=$(docker create "$REGISTRY/bundle:$version" bundle)
  mkdir -p "$target.tmp"
  docker cp "$container:/bundle/." "$target.tmp/"
  docker rm "$container" >/dev/null
  mv "$target.tmp" "$target"
}

check_env() {
  # Garde-fou 2 (ADR 0042) : jamais de DSN propriétaire sur le VPS, Neon en
  # sslmode=require, Redis interne, domaine en https. Le contrôle est celui de CETTE
  # version : une version ancienne peut refuser un fichier écrit pour une plus récente.
  # Rend 1 sans arrêter le script (un retour arrière doit pouvoir le constater) ; les
  # refus vont dans le journal, pas seulement sur le terminal.
  local version=$1 refusals line
  if refusals=$(python3 "$RELEASES_DIR/$version/check_runtime_env.py" --require-vps \
    --env-file "$ENV_FILE" --compose "$RELEASES_DIR/$version/docker-compose.yml" 2>&1 >/dev/null); then
    return 0
  fi
  log "$version refuse $ENV_FILE (check_runtime_env.py --require-vps de $version) :"
  while IFS= read -r line; do
    [[ -n "$line" ]] && log "  $line"
  done <<<"$refusals"
  return 1
}

accepts_env() {
  # La version $1 démarrerait-elle avec le fichier de secrets actuel ? Sans rien lancer.
  fetch_bundle "$1" && check_env "$1"
}

cannot_roll_back() {
  # Vu le 2026-10-29 : la nouvelle version ne démarre pas, la précédente refuse le
  # fichier de secrets écrit pour la nouvelle. Rien n'est relancé : on dit quoi faire.
  local version=$1 previous=$2
  log "RETOUR IMPOSSIBLE : $previous refuse $ENV_FILE (refus ci-dessus)."
  log "La pile $STACK tourne sur $version, qui ne répond pas : la page de maintenance est servie."
  log "À faire à la main, au choix :"
  log "  1. réparer $version (journaux : docker compose -p $PROJECT logs --tail 100 api worker),"
  log "     puis : sudo -u deploy $COGES_ROOT/deploy.sh $STACK $version"
  log "  2. ou remettre dans $ENV_FILE ce que $previous exige (refus ci-dessus),"
  log "     puis : sudo -u deploy $COGES_ROOT/deploy.sh $STACK $previous"
  log "     (pas « rollback » : il viserait la version d'avant $previous)"
}

curl_through_caddy() {
  # Par Caddy, comme un navigateur, sans dépendre du DNS de la machine.
  local path=$1 insecure=()
  [[ "$COGES_DEPLOY_INSECURE" == 1 ]] && insecure=(--insecure)
  curl --silent --show-error --fail --max-time 10 "${insecure[@]}" \
    --resolve "$DOMAIN:$COGES_HTTPS_PORT:127.0.0.1" \
    "https://$DOMAIN:$COGES_HTTPS_PORT$path"
}

verify() {
  # Les réponses sont gardées dans une variable avant d'être lues : `curl … | grep -q`
  # sous `pipefail` échoue dès que grep s'arrête au premier mot trouvé et que curl
  # reçoit SIGPIPE — une version saine passait pour cassée (ADR 0088).
  local deadline=$((SECONDS + COGES_DEPLOY_WAIT)) ready login
  while ((SECONDS < deadline)); do
    ready=$(curl_through_caddy /api/v1/health/ready 2>/dev/null || true)
    login=$(curl_through_caddy /login 2>/dev/null || true)
    if [[ "$ready" == *'"status":"ok"'* && "$login" == *Connexion* ]]; then
      return 0
    fi
    sleep 5
  done
  return 1
}

docker_network() {
  # Réseau de Caddy partagé par les deux piles ; l'API ne croit X-Forwarded-For que de lui.
  if ! docker network inspect coges_edge >/dev/null 2>&1; then
    docker network create --driver bridge --subnet 172.30.0.0/24 coges_edge >/dev/null
  fi
}

start() {
  # Chaque étape rend son échec : appelée dans un `if`, la fonction ne s'arrête plus
  # d'elle-même (`set -e` y est suspendu), et un `up -d` raté doit déclencher le retour.
  # Code 2 : le fichier de secrets est refusé avant tout changement.
  local version=$1
  fetch_bundle "$version" || return 1
  check_env "$version" || return 2
  # Une version est immuable : une image déjà présente n'est pas retéléchargée.
  compose "$version" pull --quiet --policy missing || return 1
  compose "$version" up -d --remove-orphans || return 1
  # Hors du mode `cloudflare`, un tunnel resté allumé (retour arrière, secours) n'est pas
  # arrêté par `up` : son profil n'est pas actif, ce n'est donc pas un « orphelin ».
  if [[ "$STACK" == production && "$TUNNEL" == 0 ]]; then
    compose "$version" --profile tunnel rm --stop --force cloudflared >/dev/null || return 1
  fi
}

prune_images() {
  # Le disque du VPS ne garde que les versions qui peuvent encore servir : celle qui
  # tourne et la précédente, de chaque pile (ADR 0088). Une image encore utilisée par
  # un conteneur refuse de partir : ce n'est pas une erreur.
  local keep=() file image
  for file in "$STATE_DIR"/*.version "$STATE_DIR"/*.previous; do
    [[ -f "$file" ]] && keep+=("$(cat "$file")")
  done
  while read -r image; do
    [[ "$image" == "$REGISTRY"/*:* ]] || continue
    [[ " ${keep[*]} " == *" ${image##*:} "* ]] && continue
    docker image rm "$image" >/dev/null 2>&1 || true
  done < <(docker image ls --format '{{.Repository}}:{{.Tag}}' 2>/dev/null || true)
}

deploy() {
  local version=$1 previous="" status=0 fallback=1
  [[ -f "$CURRENT_FILE" ]] && previous=$(cat "$CURRENT_FILE")
  log "déploiement de $version (actuelle : ${previous:-aucune})"
  registry_login
  docker_network
  # Avant de toucher à la pile : la version en place accepte-t-elle encore le fichier ?
  # Sinon, un échec de $version ne pourrait pas être rattrapé tout seul.
  if [[ -n "$previous" && "$previous" != "$version" ]] && ! accepts_env "$previous"; then
    fallback=0
    log "ATTENTION : pas de retour automatique possible si $version échoue ($previous refuse $ENV_FILE)."
  fi
  if start "$version"; then status=0; else status=$?; fi
  if ((status == 2)); then
    die "$ENV_FILE refusé par $version : rien n'a été changé, $previous tourne toujours"
  fi
  if ((status == 0)) && verify; then
    if [[ -n "$previous" && "$previous" != "$version" ]]; then
      echo "$previous" >"$PREVIOUS_FILE"
    fi
    echo "$version" >"$CURRENT_FILE"
    log "OK : $version répond sur https://$DOMAIN"
    prune_images
    return 0
  fi
  log "$version n'a pas démarré ou ne répond pas après ${COGES_DEPLOY_WAIT} s"
  if [[ -n "$previous" && "$previous" != "$version" ]] && ((fallback == 0)); then
    cannot_roll_back "$version" "$previous"
  elif [[ -n "$previous" && "$previous" != "$version" ]]; then
    log "retour automatique à $previous"
    if start "$previous" && verify; then
      log "retour à $previous : OK"
    else
      log "retour à $previous : la version précédente ne répond pas non plus"
    fi
  fi
  die "déploiement de $version refusé"
}

case "$ACTION" in
  status)
    echo "pile       : $STACK ($PROJECT)"
    echo "version    : $(cat "$CURRENT_FILE" 2>/dev/null || echo aucune)"
    echo "précédente : $(cat "$PREVIOUS_FILE" 2>/dev/null || echo aucune)"
    docker compose -p "$PROJECT" ps --format 'table {{.Service}}\t{{.Status}}' || true
    ;;
  stop)
    version=$(cat "$CURRENT_FILE" 2>/dev/null) || die "aucune version de préprod connue"
    compose "$version" down
    log "préproduction arrêtée ($version)"
    ;;
  rollback)
    [[ -f "$PREVIOUS_FILE" ]] || die "aucune version précédente connue"
    target=$(cat "$PREVIOUS_FILE")
    deploy "$target"
    ;;
  *)
    deploy "$ACTION"
    ;;
esac
