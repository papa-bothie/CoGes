"""Tout ce que `app/` importe est installé dans les images (correctif de l'ADR 0104).

Les images `api` et `worker` font `uv sync --no-dev` : seules `[project].dependencies`
(et le groupe `ml`, pour le worker) y sont. `app/core/cloudflare_access.py` importait
`httpx`, présent seulement dans le groupe `dev` : les tests passaient, l'image de
production ne démarrait pas (`ModuleNotFoundError: No module named 'httpx'`).

Chaque `import` de `app/` est lu dans le texte (`ast`), y compris ceux cachés dans une
fonction : un paquet tiers doit être déclaré **directement**, jamais seulement obtenu par
la dépendance d'une dépendance (une mise à jour pourrait le retirer). Le groupe `ml`
reste confiné au worker par `test_api_has_no_ml_dependency.py`.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
PYPROJECT = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))


def _name(requirement: str) -> str:
    """`pyjwt[crypto]>=2.15` → `pyjwt` (forme normalisée de la PEP 503)."""
    match = re.match(r"[A-Za-z0-9._-]+", requirement)
    assert match is not None, requirement
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


RUNTIME = {_name(item) for item in PYPROJECT["project"]["dependencies"]}
ML = {_name(item) for item in PYPROJECT["dependency-groups"]["ml"]}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _third_party() -> dict[str, set[str]]:
    """Module de premier niveau → fichiers de `app/` qui l'importent."""
    found: dict[str, set[str]] = {}
    for path in sorted(APP.rglob("*.py")):
        for module in _imported_modules(path):
            if module in sys.stdlib_module_names or module in {"app", "__future__"}:
                continue
            found.setdefault(module, set()).add(str(path.relative_to(BACKEND)))
    return found


def test_every_third_party_import_of_app_is_a_runtime_dependency() -> None:
    distributions = packages_distributions()
    missing: list[str] = []
    for module, files in sorted(_third_party().items()):
        names = {_name(dist) for dist in distributions.get(module, [])}
        if not names:
            missing.append(f"{module} (introuvable, importé par {sorted(files)})")
        elif not names & (RUNTIME | ML):
            missing.append(
                f"{module} → {sorted(names)} : absent de [project].dependencies "
                f"(importé par {sorted(files)})"
            )
    assert missing == [], "paquets importés par app/ mais absents des images :\n" + "\n".join(
        missing
    )


def test_the_check_sees_the_imports_that_matter() -> None:
    """Le test ne passe pas à vide : il voit bien les paquets tiers d'`app/`."""
    third_party = _third_party()
    assert {"fastapi", "sqlalchemy", "celery", "jwt", "httpx"} <= set(third_party)
