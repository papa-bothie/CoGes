"""Garde-fou des lots « sur site » (ADR 0124) : ajouter, ne rien modifier.

Les fichiers du VPS, le code de l'application, les migrations et le déploiement de la
production ne changent pas dans une branche `feat/sur-site-*` : c'est ce qui garantit aux
utilisateurs actuels qu'ils ne verront aucune différence. Le workflow « Sur site » lance
ce script sur ces pull requests ; il compare la branche à sa base et ÉCHOUE en nommant
chaque fichier protégé modifié, ajouté ou supprimé.

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="branche de base de la PR")
    parser.add_argument("--paths", nargs="*", help="chemins à juger, sans interroger git")
    args = parser.parse_args(argv)

    paths = args.paths if args.paths is not None else changed_paths(args.base)
    touched = protected_among(paths)
    for path in touched:
        print(
            f"REFUS — {path} est un chemin protégé : un lot sur site ajoute, il ne modifie pas",
            file=sys.stderr,
        )
    if touched:
        print(
            "Ces fichiers servent les utilisateurs actuels. Si le changement est nécessaire, "
            "il se demande au propriétaire, avec sa raison (ADR 0124).",
            file=sys.stderr,
        )
        return 1
    print(f"OK — aucun chemin protégé parmi {len(paths)} fichier(s) modifié(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
