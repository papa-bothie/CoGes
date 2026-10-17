#!/usr/bin/env bash
# Préparation d'un VPS Ubuntu 24.04 LTS neuf pour CoGes (ADR 0083). À lancer en root,
# une fois, puis à chaque fois qu'on veut remettre la machine d'aplomb : chaque étape
# vérifie d'abord ce qui est déjà en place (idempotent).
#
#   sudo ./bootstrap.sh --dry-run            # montre ce qui serait fait, ne change rien
#   sudo ./bootstrap.sh                      # applique
#   sudo ./bootstrap.sh --ssh-port 2222 --hostname coges-prod
#
# Ce que fait le script : fuseau UTC et locale, nom de machine, utilisateurs `coges`
# (administrateur, sudo) et `deploy` (déploiement, sans sudo), SSH par clé seulement,
# pare-feu ufw (SSH, 80, 443), fail2ban, mises à jour de sécurité automatiques
# (redémarrage à 05 h 15 UTC si nécessaire), 2 Go de swap, réglages noyau pour Redis,
# Docker Engine et son plugin compose depuis le dépôt officiel, limites de journald,
# arborescence /opt/coges, /etc/coges et /var/log/coges, installation de deploy.sh.
#
# Ce qu'il ne fait PAS : déposer les secrets (/etc/coges/*.env), créer la clé bridée de
# GitHub Actions, ni lancer CoGes. Voir docs/runbooks/vps.md.

set -euo pipefail

SSH_PORT=22
HOSTNAME_WANTED=""
ADMIN_USER=coges
DEPLOY_USER=deploy
DRY_RUN=0
SWAP_SIZE_GB=2
REBOOT_TIME="05:15"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

usage() {
  sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --ssh-port)
      SSH_PORT=${2:?--ssh-port attend un numéro}
      shift
      ;;
    --hostname)
      HOSTNAME_WANTED=${2:?--hostname attend un nom}
      shift
      ;;
    -h | --help) usage ;;
    *) usage ;;
  esac
  shift
done

if ! [[ "$SSH_PORT" =~ ^[0-9]+$ ]] || ((SSH_PORT < 1 || SSH_PORT > 65535)); then
  echo "port SSH invalide : $SSH_PORT" >&2
  exit 2
fi

step() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }

# Toute commande qui change la machine passe par `run` : en --dry-run, elle est affichée.
run() {
  if ((DRY_RUN)); then
    printf '   [essai] %s\n' "$*"
  else
    "$@"
  fi
}

# Écrit un fichier seulement si son contenu change (et le dit).
write_file() {
  local path=$1 mode=$2 content
  content=$(cat)
  if [[ -f "$path" ]] && [[ "$(cat "$path")" == "$content" ]]; then
    note "$path : déjà à jour"
    return 1
  fi
  if ((DRY_RUN)); then
    note "[essai] écrirait $path"
    return 0
  fi
  install -d "$(dirname "$path")"
  printf '%s\n' "$content" >"$path"
  chmod "$mode" "$path"
  note "$path : écrit"
  return 0
}

if ((!DRY_RUN)) && [[ $EUID -ne 0 ]]; then
  echo "À lancer en root (sudo ./bootstrap.sh)." >&2
  exit 1
fi

# shellcheck source=/dev/null
. /etc/os-release
if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "Ubuntu 24.04 LTS attendu (trouvé : ${PRETTY_NAME:-inconnu})." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

# ------------------------------------------------------------------ 1. système de base
step "Fuseau horaire, locale, nom de machine"
if [[ "$(timedatectl show -p Timezone --value 2>/dev/null || echo)" != UTC ]]; then
  run timedatectl set-timezone UTC
else
  note "fuseau : déjà UTC"
fi
if ! locale -a 2>/dev/null | grep -qi '^c\.utf-\?8$'; then
  run apt-get install -y -qq locales
fi
run localectl set-locale LANG=C.UTF-8 || true
if [[ -n "$HOSTNAME_WANTED" && "$(hostname)" != "$HOSTNAME_WANTED" ]]; then
  run hostnamectl set-hostname "$HOSTNAME_WANTED"
fi

step "Paquets de base"
run apt-get update -qq
run apt-get install -y -qq ca-certificates curl gnupg ufw fail2ban unattended-upgrades \
  apt-listchanges python3 jq openssl

# ------------------------------------------------------------------ 2. utilisateurs
step "Utilisateurs $ADMIN_USER (sudo) et $DEPLOY_USER (sans sudo)"
if ! id "$ADMIN_USER" >/dev/null 2>&1; then
  run adduser --disabled-password --gecos "Administrateur CoGes" "$ADMIN_USER"
fi
run usermod -aG sudo "$ADMIN_USER"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  run adduser --disabled-password --gecos "Déploiement CoGes (GitHub Actions)" "$DEPLOY_USER"
fi

# Reprend la clé de l'utilisateur d'origine (root ou ubuntu chez Infomaniak) si
# l'administrateur n'en a pas encore.
admin_keys="/home/$ADMIN_USER/.ssh/authorized_keys"
if [[ ! -s "$admin_keys" ]]; then
  for source_keys in /root/.ssh/authorized_keys /home/ubuntu/.ssh/authorized_keys; do
    if [[ -s "$source_keys" ]]; then
      note "clés reprises de $source_keys"
      run install -d -m 0700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/$ADMIN_USER/.ssh"
      run install -m 0600 -o "$ADMIN_USER" -g "$ADMIN_USER" "$source_keys" "$admin_keys"
      break
    fi
  done
fi
run install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
if [[ ! -e "/home/$DEPLOY_USER/.ssh/authorized_keys" ]]; then
  run install -m 0600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /dev/null \
    "/home/$DEPLOY_USER/.ssh/authorized_keys"
fi

# ------------------------------------------------------------------ 3. SSH
step "SSH : clé seulement, pas de root, port $SSH_PORT"
has_key=0
if [[ -s "$admin_keys" ]] && grep -qE '^(ssh-(ed25519|rsa)|ecdsa-sha2-|sk-)' "$admin_keys"; then
  has_key=1
fi
if ((has_key == 0)) && ((!DRY_RUN)); then
  # Refus volontaire : sans clé, couper le mot de passe enfermerait tout le monde dehors.
  echo "REFUS : aucune clé dans $admin_keys. Déposez votre clé publique" >&2
  echo "        (ssh-copy-id $ADMIN_USER@<ip>) puis relancez le script." >&2
  exit 1
fi
if write_file /etc/ssh/sshd_config.d/10-coges.conf 0644 <<EOF; then
# CoGes (bootstrap.sh) : connexion par clé seulement, jamais en root.
Port $SSH_PORT
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowUsers $ADMIN_USER $DEPLOY_USER
EOF
  run sshd -t
  # Ubuntu 24.04 : le port vient aussi de ssh.socket ; recharger les deux.
  run systemctl daemon-reload
  run systemctl restart ssh.socket 2>/dev/null || true
  run systemctl reload ssh || run systemctl restart ssh
fi

# ------------------------------------------------------------------ 4. pare-feu
step "Pare-feu ufw : entrée fermée sauf SSH ($SSH_PORT), 80 et 443"
run ufw default deny incoming
run ufw default allow outgoing
run ufw allow "$SSH_PORT/tcp" comment ssh
run ufw allow 80/tcp comment http
run ufw allow 443/tcp comment https
run ufw allow 443/udp comment http3
if [[ "$SSH_PORT" != 22 ]]; then
  run ufw delete allow 22/tcp >/dev/null 2>&1 || true
fi
run ufw --force enable
note "Docker publie 80 et 443 lui-même (Caddy) : ce sont les seuls ports exposés."

step "fail2ban sur SSH"
if write_file /etc/fail2ban/jail.d/coges-sshd.conf 0644 <<EOF; then
[sshd]
enabled = true
port = $SSH_PORT
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
EOF
  run systemctl enable --now fail2ban
  run systemctl restart fail2ban
fi

# ------------------------------------------------------------------ 5. mises à jour
step "Mises à jour de sécurité automatiques (redémarrage à $REBOOT_TIME UTC si nécessaire)"
write_file /etc/apt/apt.conf.d/52coges-unattended 0644 <<EOF || true
// CoGes (bootstrap.sh) : sécurité seulement. Redémarrage hors des tâches de nuit de
// beat.py (01 h 00 à 04 h 30 UTC, scan des dettes à 06 h 00).
Unattended-Upgrade::Allowed-Origins {
        "\${distro_id}:\${distro_codename}-security";
        "\${distro_id}ESMApps:\${distro_codename}-apps-security";
        "\${distro_id}ESM:\${distro_codename}-infra-security";
};
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "$REBOOT_TIME";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
write_file /etc/apt/apt.conf.d/20auto-upgrades 0644 <<'EOF' || true
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# ------------------------------------------------------------------ 6. mémoire
step "Swap de ${SWAP_SIZE_GB} Go, réglages noyau (Redis)"
if ! swapon --show=NAME --noheadings | grep -q '^/swapfile$'; then
  if [[ ! -f /swapfile ]]; then
    run fallocate -l "${SWAP_SIZE_GB}G" /swapfile
    run chmod 600 /swapfile
    run mkswap /swapfile
  fi
  run swapon /swapfile
else
  note "swap : déjà actif"
fi
if ! grep -q '^/swapfile ' /etc/fstab; then
  if ((DRY_RUN)); then
    note "[essai] ajouterait /swapfile à /etc/fstab"
  else
    echo '/swapfile none swap sw 0 0' >>/etc/fstab
  fi
fi
if write_file /etc/sysctl.d/90-coges.conf 0644 <<'EOF'; then
# CoGes : swap en dernier recours ; Redis exige l'overcommit pour ses sauvegardes AOF.
vm.swappiness = 10
vm.overcommit_memory = 1
EOF
  run sysctl --system >/dev/null
fi

step "journald : 500 Mo au plus, 1 mois"
if write_file /etc/systemd/journald.conf.d/coges.conf 0644 <<'EOF'; then
[Journal]
SystemMaxUse=500M
MaxRetentionSec=1month
EOF
  run systemctl restart systemd-journald
fi

# ------------------------------------------------------------------ 7. Docker
step "Docker Engine et plugin compose (dépôt officiel)"
if ! command -v docker >/dev/null 2>&1; then
  run install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    run curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    run chmod a+r /etc/apt/keyrings/docker.asc
  fi
  arch=$(dpkg --print-architecture)
  write_file /etc/apt/sources.list.d/docker.list 0644 <<EOF || true
deb [arch=$arch signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable
EOF
  run apt-get update -qq
  run apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
    docker-compose-plugin
else
  note "docker : déjà installé"
fi
if write_file /etc/docker/daemon.json 0644 <<'EOF'; then
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "5" },
  "live-restore": true,
  "no-new-privileges": true
}
EOF
  run systemctl restart docker
fi
run systemctl enable --now docker
# `deploy` pilote Docker : c'est un droit de root en pratique. Sa clé est bridée sur
# deploy.sh (command=…), et c'est la seule chose qu'elle peut lancer.
run usermod -aG docker "$DEPLOY_USER"
run usermod -aG docker "$ADMIN_USER"

# ------------------------------------------------------------------ 8. CoGes
step "Arborescence CoGes et deploy.sh"
run install -d -m 0755 -o root -g root /opt/coges
run install -d -m 0755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /opt/coges/state /opt/coges/releases
run install -d -m 0750 -o root -g "$DEPLOY_USER" /etc/coges
run install -d -m 0755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /var/log/coges
# Propriété de root : la clé bridée lance ce fichier, elle ne doit pas pouvoir le changer.
run install -m 0755 -o root -g root "$SCRIPT_DIR/deploy.sh" /opt/coges/deploy.sh
run install -m 0755 -o root -g root "$SCRIPT_DIR/check.sh" /opt/coges/check.sh

step "Versions installées"
if ((!DRY_RUN)); then
  {
    date -u +%Y-%m-%dT%H:%M:%SZ
    docker --version
    docker compose version
    ufw version | head -1
    fail2ban-client --version | head -1
  } | tee -a /var/log/coges/bootstrap.log
fi

cat <<EOF

Terminé.$( ((DRY_RUN)) && echo " (essai : rien n'a été changé)")
Ensuite (docs/runbooks/vps.md, « Première installation ») :
  1. tester une NOUVELLE connexion : ssh -p $SSH_PORT $ADMIN_USER@<ip>  (garder l'ancienne ouverte) ;
  2. déposer /etc/coges/coges.env (modèle coges.env.example), root:$DEPLOY_USER, mode 0640 ;
  3. déposer /etc/coges/ghcr-user et /etc/coges/ghcr-token (jeton GitHub en lecture seule) ;
  4. premier déploiement : sudo -u $DEPLOY_USER /opt/coges/deploy.sh production vX.Y.Z
EOF
