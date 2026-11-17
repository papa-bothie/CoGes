"""Garde-fou des lots « sur site » (ADR 0124) : ajouter, ne rien modifier.

Les fichiers du VPS, le code de l'application, les migrations et le déploiement de la
production ne changent pas dans une branche `feat/sur-site-*` : c'est ce qui garantit aux
utilisateurs actuels qu'ils ne verront aucune différence. Le workflow « Sur site » lance
ce script sur ces pull requests ; il compare la branche à sa base et ÉCHOUE en nommant
chaque fichier protégé modifié, ajouté ou supprimé.

Dérogations (ADR 0125) : un lot qui doit toucher un fichier protégé le nomme dans
`DEROGATIONS`, avec sa raison et son lot. Ce fichier n'est accepté que si le diff ne
retire **aucune** ligne (`git diff --numstat` : 0 suppression) ; une ligne modifiée ou
retirée le refuse comme avant. Un test épingle la table : l'élargir se voit en revue.

Usage : python deploy/onprem/check_protected_paths.py [--base origin/main]
        python deploy/onprem/check_protected_paths.py --paths FICHIER…   (sans git)
Bibliothèque standard seulement.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys

#: Chemins protégés. `/**` : tout ce qui est sous le dossier ; sinon un motif de fichier.
PROTECTED = (
    "deploy/vps/**",
    "deploy/scripts/**",
    "deploy/postgres/**",
    "deploy/sql/**",
    "docker-compose.yml",
    "backend/app/**",
    "backend/migrations/**",
    "backend/Dockerfile.*",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "frontend/**",
    "frontend-admin/**",
    ".github/workflows/deploy.yml",
    ".github/workflows/backup*.yml",
)


#: Fichiers protégés qu'un lot a le droit de compléter, PAR AJOUT SEULEMENT :
#: chemin → (raison, lot). Toute ligne ajoutée ici se justifie dans l'ADR du lot.
DEROGATIONS: dict[str, tuple[str, str]] = {
    "backend/app/cli.py": (
        "commandes activate-license et license-status (licence sur site, ADR 0125)",
        "lot 2",
    ),
    "backend/app/modules/platform/service.py": (
        "fonctions activate_license et license_status de la façade (ADR 0125)",
        "lot 2",
    ),
}

#: Ajouts et suppressions d'un fichier ; `None` : inconnu (fichier binaire, ou sans git).
Counts = tuple[int | None, int | None]


def is_protected(path: str) -> bool:
    path = path.strip().replace("\\", "/").removeprefix("./")
    for pattern in PROTECTED:
        if pattern.endswith("/**"):
            if path.startswith(pattern[:-2]):
                return True
        elif fnmatch.fnmatchcase(path, pattern):
            return True
    return False


def protected_among(paths: list[str]) -> list[str]:
    """Les chemins protégés parmi ceux d'une comparaison, triés."""
    return sorted({path.strip() for path in paths if path.strip() and is_protected(path)})


def changed_paths(base: str) -> list[str]:
    """Fichiers qui diffèrent entre l'ancêtre commun avec `base` et HEAD. Un renommage
    compte pour ses deux noms (`--no-renames`) : déplacer un fichier protégé le modifie."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def changed_numstat(base: str) -> dict[str, Counts]:
    """Comme `changed_paths`, avec les lignes ajoutées et supprimées de chaque fichier."""
    result = subprocess.run(
        ["git", "diff", "--numstat", "--no-renames", f"{base}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    counts: dict[str, Counts] = {}
    for line in result.stdout.splitlines():
        added, deleted, path = line.split("\t", 2)
        counts[path] = (
            int(added) if added.isdigit() else None,
            int(deleted) if deleted.isdigit() else None,
        )
    return counts


def refusals(numstat: dict[str, Counts]) -> list[str]:
    """Un message par fichier protégé refusé ; un fichier de `DEROGATIONS` passe s'il n'a
    perdu aucune ligne (nombre connu et nul)."""
    found: list[str] = []
    for path in protected_among(list(numstat)):
        if path not in DEROGATIONS:
            found.append(
                f"REFUS — {path} est un chemin protégé : un lot sur site ajoute, il ne modifie pas"
            )
            continue
        deleted = numstat[path][1]
        if deleted is None:
            found.append(
                f"REFUS — {path} : dérogation ({DEROGATIONS[path][1]}) en ajout seulement, "
                "mais le nombre de lignes supprimées est inconnu"
            )
        elif deleted > 0:
            found.append(
                f"REFUS — {path} : {deleted} ligne(s) supprimée(s) ou modifiée(s) ; la "
                f"dérogation du {DEROGATIONS[path][1]} n'admet que des ajouts"
            )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="branche de base de la PR")
    parser.add_argument("--paths", nargs="*", help="chemins à juger, sans interroger git")
    args = parser.parse_args(argv)

    # Sans git (`--paths`), les suppressions sont inconnues : aucune dérogation ne joue.
    numstat: dict[str, Counts] = (
        {path: (None, None) for path in args.paths}
        if args.paths is not None
        else changed_numstat(args.base)
    )
    paths = list(numstat)
    touched = refusals(numstat)
    for message in touched:
        print(message, file=sys.stderr)
    if touched:
        print(
            "Ces fichiers servent les utilisateurs actuels. Si le changement est nécessaire, "
            "il se demande au propriétaire, avec sa raison (ADR 0124).",
            file=sys.stderr,
        )
        return 1
    for path in protected_among(paths):
        lot, added = DEROGATIONS[path][1], numstat[path][0]
        print(f"Dérogation ({lot}) — {path} : {added} ligne(s) ajoutée(s), 0 supprimée")
    print(f"OK — aucun chemin protégé refusé parmi {len(paths)} fichier(s) modifié(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
