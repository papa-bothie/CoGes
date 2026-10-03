#!/usr/bin/env bash
# Attend qu'une adresse stable Vercel serve le nouveau déploiement de façon stable.
#
# Juste après `vercel deploy`, le domaine public bascule en quelques secondes et répond
# par intermittence 404 (NOT_FOUND de Vercel) : un seul succès ne prouve rien. On exige
# 5 réponses correctes d'affilée, à 3 s d'intervalle, 2 min au plus ; tout échec remet le
# compteur à zéro. Le jeton VERCEL_AUTOMATION_BYPASS_SECRET est envoyé s'il est défini.
#
# Usage : deploy/scripts/wait-stable.sh <url> [texte attendu dans la réponse]
set -euo pipefail

url=$1
marker=${2:-}
headers=()
if [ -n "${VERCEL_AUTOMATION_BYPASS_SECRET:-}" ]; then
  headers=(-H "x-vercel-protection-bypass: $VERCEL_AUTOMATION_BYPASS_SECRET")
fi

ok=0
for _ in $(seq 40); do
  if body=$(curl --fail --silent "${headers[@]}" "$url") \
    && { [ -z "$marker" ] || grep -qF "$marker" <<< "$body"; }; then
    ok=$((ok + 1))
    [ "$ok" -ge 5 ] && break
  else
    ok=0
  fi
  sleep 3
done
if [ "$ok" -lt 5 ]; then
  echo "::error::$url ne répond pas de façon stable"
  exit 1
fi
echo "GET $url → servie (5 fois d'affilée)"
