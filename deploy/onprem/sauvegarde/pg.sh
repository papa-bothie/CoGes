#!/bin/sh
# Outils PostgreSQL de la sauvegarde sur site (ADR 0127), dans l'image postgres:18.7-alpine
# (pg_dump, pg_restore ; pas de Python), service `sauvegarde-pg`.
#
# Le service partage le réseau du conteneur `postgres` : connexion en superutilisateur sur
# 127.0.0.1, en confiance locale, SANS mot de passe. Le dump en clair ne vit que dans le
# volume `sauvegarde-travail` (/travail), jamais dans un dossier du PC.
#
#   pg.sh dump NOM          pg_dump --format=custom de `coges` → /travail/NOM.dump, puis relu
#   pg.sh restaurer NOM BASE    /travail/NOM.dump → BASE (vide, préparée par base.py)
#   pg.sh vider             efface tout /travail (appelé dans un « finally », même après un échec)
set -eu

export PGHOST=127.0.0.1 PGUSER=postgres
travail=/travail

nom_valide() {
  case "$1" in
    "" | *[!a-z0-9.-]*) echo "ÉCHEC — nom de fichier refusé : $1" >&2; exit 2 ;;
  esac
}

case "${1:-}" in
  dump)
    nom_valide "${2:-}"
    fichier="$travail/$2.dump"
    rm -f "$fichier" "$fichier.partiel"
    # Instantané cohérent : pg_dump lit dans une seule transaction, CoGes continue de tourner.
    pg_dump --format=custom --no-password --dbname=coges --file="$fichier.partiel"
    taille=$(wc -c <"$fichier.partiel")
    [ "$taille" -gt 0 ] || { echo "ÉCHEC — dump vide" >&2; exit 1; }
    # Relu : le sommaire se lit jusqu'au bout.
    pg_restore --list "$fichier.partiel" >/dev/null || { echo "ÉCHEC — le dump ne se relit pas (pg_restore --list)" >&2; exit 1; }
    mv "$fichier.partiel" "$fichier"
    # Lisible par le service sauvegarde-py, qui le chiffre (même volume).
    chmod 0644 "$fichier"
    version=$(pg_dump --version | sed -nE 's/^pg_dump \(PostgreSQL\) ([0-9][0-9a-z.]*).*/\1/p')
    echo "dump $taille $version"
    ;;
  restaurer)
    nom_valide "${2:-}"
    case "${3:-}" in
      coges_restauration | coges_verif) ;;
      *) echo "ÉCHEC — base cible refusée : ${3:-}" >&2; exit 2 ;;
    esac
    pg_restore --dbname="$3" --exit-on-error --no-password "$travail/$2.dump"
    echo "restauree $3"
    ;;
  vider)
    # Le volume, jamais autre chose : /travail est le point de montage du volume.
    find "$travail" -mindepth 1 -delete
    echo "vide"
    ;;
  *)
    echo "usage : pg.sh dump NOM | restaurer NOM BASE | vider" >&2
    exit 2
    ;;
esac
