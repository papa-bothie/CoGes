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

DOMAIN=$(env_value COGES_DOMAIN)
[[ -n "$DOMAIN" ]] || die "COGES_DOMAIN vide dans $ENV_FILE"
[[ "$STACK" == preprod ]] && DOMAIN="preprod.$DOMAIN"
REGISTRY=$(env_value COGES_IMAGE_REGISTRY)
REGISTRY=${REGISTRY:-$REGISTRY_DEFAULT}

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
  # sslmode=require, Redis interne, domaine en https.
  python3 "$RELEASES_DIR/$1/check_runtime_env.py" --require-vps \
    --env-file "$ENV_FILE" --compose "$RELEASES_DIR/$1/docker-compose.yml" >/dev/null \
    || die "le fichier $ENV_FILE ne passe pas le contrôle (check_runtime_env.py --require-vps)"
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
  local deadline=$((SECONDS + COGES_DEPLOY_WAIT))
  while ((SECONDS < deadline)); do
    if curl_through_caddy /api/v1/health/ready 2>/dev/null | grep -q '"status":"ok"' \
      && curl_through_caddy /login 2>/dev/null | grep -q "Connexion"; then
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
  local version=$1
  fetch_bundle "$version"
  check_env "$version"
  # Une version est immuable : une image déjà présente n'est pas retéléchargée.
  compose "$version" pull --quiet --policy missing
  compose "$version" up -d --remove-orphans
}

deploy() {
  local version=$1 previous=""
  [[ -f "$CURRENT_FILE" ]] && previous=$(cat "$CURRENT_FILE")
  log "déploiement de $version (actuelle : ${previous:-aucune})"
  registry_login
  docker_network
  start "$version"
  if verify; then
    if [[ -n "$previous" && "$previous" != "$version" ]]; then
      echo "$previous" >"$PREVIOUS_FILE"
    fi
    echo "$version" >"$CURRENT_FILE"
    log "OK : $version répond sur https://$DOMAIN"
    return 0
  fi
  log "$version ne répond pas après ${COGES_DEPLOY_WAIT} s"
  if [[ -n "$previous" && "$previous" != "$version" ]]; then
    log "retour automatique à $previous"
    start "$previous"
    if verify; then
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
