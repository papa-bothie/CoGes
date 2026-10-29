#!/bin/sh
# Fichiers statiques gardés d'un déploiement à l'autre (prompt 29, ADR 0102 ; prompt 32, ADR 0103).
#
# `.next/static` est un volume : un écran resté ouvert sur l'ancienne version peut encore y
# charger ses fichiers après un déploiement. Au démarrage, ceux de cette image s'y ajoutent
# (noms à empreinte : rien n'est écrasé). Chaque build a son témoin dans le volume
# (`.coges-builds/<build>.files`, la liste de ses fichiers) ; le jour où il cesse d'être le
# build courant est noté (`<build>.retired`), et ses fichiers partent 14 jours APRÈS ce jour,
# sauf ceux qu'un build encore gardé utilise aussi.
#
# Rien ici ne doit empêcher le front de démarrer : pas de `set -e`, chaque étape tolère l'échec.
set -u
root=${STATIC_ROOT:-/srv/front}
build="$root/static-build"
target="$root/.next/static"
meta="$target/.coges-builds"
keep_seconds=$((14 * 24 * 3600))
now=${STATIC_NOW:-$(date +%s)}

cleanup() {
  mkdir -p "$meta" || return 0
  # Identifiant du build : l'empreinte de la liste de ses fichiers (noms déjà à empreinte).
  list=$(mktemp) || return 0
  (cd "$build" && find . -type f | LC_ALL=C sort) > "$list" || return 0
  id=$(cksum < "$list" | cut -d ' ' -f 1)

  # Copie sans rien écraser (`cp -n` n'est plus portable avec coreutils récents).
  while IFS= read -r path; do
    dest="$target/${path#./}"
    [ -e "$dest" ] && continue
    mkdir -p "$(dirname "$dest")" && cp "$build/${path#./}" "$dest"
  done < "$list"

  # Fichiers présents sans témoin (volume d'avant ce script) : un build ancien, retiré ce jour.
  known=$(mktemp) || return 0
  cat "$list" "$meta"/*.files 2>/dev/null | LC_ALL=C sort -u > "$known"
  orphans=$(mktemp) || return 0
  (cd "$target" && find . -type f ! -path './.coges-builds/*' | LC_ALL=C sort) \
    | LC_ALL=C comm -23 - "$known" > "$orphans"
  if [ -s "$orphans" ]; then
    mv "$orphans" "$meta/orphans-$now.files" && echo "$now" > "$meta/orphans-$now.retired"
  fi

  # Ce build redevient (ou reste) courant ; tout autre build cesse de l'être maintenant.
  cp "$list" "$meta/$id.files" && rm -f "$meta/$id.retired"
  for files in "$meta"/*.files; do
    [ -e "$files" ] || continue
    other=$(basename "$files" .files)
    [ "$other" = "$id" ] && continue
    [ -e "$meta/$other.retired" ] || echo "$now" > "$meta/$other.retired"
  done

  # Fichiers encore utiles : ceux du build courant et des builds retirés il y a moins de 14 jours.
  alive=$(mktemp) || return 0
  expired=""
  for files in "$meta"/*.files; do
    [ -e "$files" ] || continue
    other=$(basename "$files" .files)
    retired=$(cat "$meta/$other.retired" 2>/dev/null || echo "")
    if [ -n "$retired" ] && [ $((now - retired)) -ge "$keep_seconds" ]; then
      expired="$expired $other"
    else
      cat "$files" >> "$alive"
    fi
  done
  LC_ALL=C sort -u -o "$alive" "$alive"
  for other in $expired; do
    LC_ALL=C sort -u "$meta/$other.files" | LC_ALL=C comm -23 - "$alive" | while IFS= read -r path; do
      rm -f "$target/${path#./}"
    done
    rm -f "$meta/$other.files" "$meta/$other.retired"
  done
  find "$target" -mindepth 1 -type d -empty ! -path "$meta" -delete 2>/dev/null
  rm -f "$list" "$known" "$orphans" "$alive"
  return 0
}

cleanup || echo "static-entrypoint : nettoyage des anciens fichiers ignoré (erreur)" >&2
exec "$@"
