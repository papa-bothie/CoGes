#!/bin/sh
# Fichiers statiques gardés d'un déploiement à l'autre (prompt 29, ADR 0102).
#
# `.next/static` est un volume : un écran resté ouvert sur l'ancienne version peut encore y
# charger ses fichiers après un déploiement. Au démarrage, ceux de cette image s'y ajoutent
# (noms à empreinte : rien n'est écrasé), puis ce qui n'a pas servi depuis 14 jours disparaît.
set -eu
root=${STATIC_ROOT:-/srv/front}
build="$root/static-build"
target="$root/.next/static"
mkdir -p "$target"
cp -R -n "$build/." "$target/"
# Les fichiers de cette image sont « neufs » : ils ne partent pas avant 14 jours.
find "$build" -type f | while read -r file; do
  touch "$target/${file#"$build"/}" 2>/dev/null || true
done
find "$target" -type f -mtime +14 -delete
find "$target" -mindepth 1 -type d -empty -delete
exec "$@"
