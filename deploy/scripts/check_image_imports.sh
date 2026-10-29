#!/usr/bin/env bash
# Une image construite importe-t-elle son point d'entrée ? (correctif de l'ADR 0104)
#
#   deploy/scripts/check_image_imports.sh api    IMAGE
#   deploy/scripts/check_image_imports.sh worker IMAGE
#
# Les images font `uv sync --no-dev` : un paquet du seul groupe `dev` importé par app/
# passe tous les tests et casse la production au démarrage (httpx, 3cafc49). Ce contrôle
# lance l'image telle quelle, sans base ni Redis : importer ne se connecte à rien.
#   api    : app.main (l'application FastAPI, tous ses routers et middlewares) ;
#   worker : l'application Celery et ses modules de tâches (`include`), le relais de
#            l'outbox et la sonde de santé (les quatre commandes du compose).
set -euo pipefail

usage() {
  sed -n '4,5p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

[[ $# -eq 2 ]] || usage
kind=$1
image=$2

case "$kind" in
  api)
    probe='import app.main'
    ;;
  worker)
    probe='from app.workers.celery_app import celery_app
celery_app.loader.import_default_modules()
import app.workers.relay, app.workers.health'
    ;;
  *) usage ;;
esac

if ! docker run --rm --network none --entrypoint python "$image" -c "$probe"; then
  echo "REFUS — l'image $image ($kind) n'importe pas son point d'entrée" >&2
  exit 1
fi
echo "OK — l'image $image ($kind) importe son point d'entrée"
