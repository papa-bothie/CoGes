"""Retire du sommaire d'une sauvegarde les droits internes à Neon (docs/runbooks/sauvegarde.md).

Lancé par `restore_backup.sh` entre `pg_restore --list` et `pg_restore --use-list` :

  pg_restore --list … | python3 deploy/scripts/restore_toc_filter.py <liste à restaurer>

Une base Neon porte des droits par défaut de ses rôles de service, par exemple
`ALTER DEFAULT PRIVILEGES FOR ROLE cloud_admin IN SCHEMA public GRANT ALL ON SEQUENCES TO
neon_superuser`. Restaurés ailleurs (ou sur une autre branche par un rôle qui n'est pas
`cloud_admin`), ils échouent en « permission denied » et arrêtent `pg_restore`. Sont
retirées les entrées `DEFAULT ACL` et `ACL` dont le propriétaire est `cloud_admin`,
`neon_superuser` ou un rôle `neon_*` ; jamais celles d'un rôle `coges_*`, ni aucune autre
entrée. Le sommaire ne contient que des noms d'objets, aucune donnée.

Sortie : le nombre d'entrées retirées et leurs titres, puis la liste écrite dans le
fichier donné (le sommaire d'origine moins ces lignes, dans le même ordre).
Bibliothèque standard seulement.
"""

from __future__ import annotations

import re
import sys

# « 4321; 826 16385 DEFAULT ACL public DEFAULT PRIVILEGES FOR SEQUENCES cloud_admin »
ENTRY = re.compile(r"^\d+; \d+ \d+ (?P<title>.+)$")
NEON_ROLES = {"cloud_admin", "neon_superuser"}


def is_neon_acl(line: str) -> bool:
    match = ENTRY.match(line.rstrip("\n"))
    if not match:
        return False  # commentaire ou ligne vide du sommaire
    title = match["title"]
    if not (title.startswith("DEFAULT ACL ") or title.startswith("ACL ")):
        return False
    owner = title.rsplit(" ", 1)[-1]
    if owner.startswith("coges_"):
        return False
    return owner in NEON_ROLES or owner.startswith("neon_")


def split(lines: list[str]) -> tuple[list[str], list[str]]:
    """(lignes à garder, titres des entrées retirées)."""
    kept: list[str] = []
    excluded: list[str] = []
    for line in lines:
        if is_neon_acl(line):
            match = ENTRY.match(line.rstrip("\n"))
            assert match
            excluded.append(match["title"])
        else:
            kept.append(line)
    return kept, excluded


def main() -> int:
    if len(sys.argv) != 2:
        print("usage : … | restore_toc_filter.py <liste à restaurer>", file=sys.stderr)
        return 2
    kept, excluded = split(sys.stdin.readlines())
    if not any(ENTRY.match(line) for line in kept):
        print("sommaire vide ou illisible", file=sys.stderr)
        return 1
    with open(sys.argv[1], "w", encoding="utf-8") as out:
        out.writelines(kept)
    print(f"    {len(excluded)} entrée(s) interne(s) à Neon exclue(s)")
    for title in excluded:
        print(f"      {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
