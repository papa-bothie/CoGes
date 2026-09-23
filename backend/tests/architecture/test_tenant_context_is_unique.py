"""Le contexte tenant n'est posé qu'à un seul endroit du code.

Point résiduel n° 1 du § 12.1 : « c'est le seul endroit où une erreur
d'implémentation peut encore produire une fuite entre tenants ». Ces tests sont la
revue de code automatisée que le document réclame.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
MIGRATIONS_ROOT = Path(__file__).resolve().parents[2] / "migrations"

# Seul module autorisé à poser le contexte.
TENANCY_MODULE = APP_ROOT / "core" / "tenancy.py"

# `SET ...` en SQL, sauf `SET LOCAL`. Le `\b` initial évite de capturer « RESET ».
SET_WITHOUT_LOCAL = re.compile(r"\bSET\s+(?!LOCAL\b)[A-Za-z_]", re.IGNORECASE)

# `SET search_path = ...` dans un `CREATE FUNCTION` est un **attribut de fonction** :
# il ne vaut que pendant l'appel, ne survit pas à la connexion, et il est au
# contraire exigé sur toute fonction `SECURITY DEFINER`. Toléré dans les migrations,
# toujours interdit dans `app/`.
FUNCTION_SEARCH_PATH = re.compile(r"\bSET\s+search_path\s*=", re.IGNORECASE)

# Équivalent Python d'un `SET` de session : le 3e argument de set_config vaut false.
SESSION_SCOPED_SET_CONFIG = re.compile(r"set_config\s*\([^)]*,\s*(false|False)\s*\)")


def _python_sources(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_no_sql_set_without_local() -> None:
    """Aucun `SET` de session : un `SET LOCAL` meurt au COMMIT, un `SET` survit au pool."""
    offenders: list[str] = []
    for source in _python_sources(APP_ROOT) + _python_sources(MIGRATIONS_ROOT):
        in_migrations = MIGRATIONS_ROOT in source.parents
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
            if not SET_WITHOUT_LOCAL.search(line):
                continue
            if in_migrations and FUNCTION_SEARCH_PATH.search(line):
                continue
            offenders.append(f"{source.name}:{number}: {line.strip()}")

    assert offenders == [], "SET sans LOCAL détecté :\n" + "\n".join(offenders)


def test_set_config_is_never_session_scoped() -> None:
    """`set_config(..., false)` est un `SET` de session déguisé : interdit partout."""
    offenders: list[str] = []
    for source in _python_sources(APP_ROOT) + _python_sources(MIGRATIONS_ROOT):
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
            if SESSION_SCOPED_SET_CONFIG.search(line):
                offenders.append(f"{source.name}:{number}: {line.strip()}")

    assert offenders == [], "set_config en portée session détecté :\n" + "\n".join(offenders)


def _executable_text(source: Path) -> str:
    """Code exécutable du fichier : chaînes et identifiants, sans commentaires ni docstrings.

    Un commentaire qui *parle* du contexte tenant est légitime ; une chaîne SQL qui
    le *pose* ne l'est pas. Seul l'AST permet de faire la différence.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstring_nodes.add(id(body[0].value))

    fragments: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstring_nodes:
                fragments.append(node.value)
        elif isinstance(node, ast.Name):
            fragments.append(node.id)
        elif isinstance(node, ast.Attribute):
            fragments.append(node.attr)
    return "\n".join(fragments)


def test_only_tenancy_module_sets_the_context() -> None:
    """Un seul fichier de `app/` pose réellement `app.company_id`."""
    offenders: list[str] = []
    for source in _python_sources(APP_ROOT):
        if source == TENANCY_MODULE:
            continue
        executable = _executable_text(source)
        if "set_config" in executable or "app.company_id" in executable:
            offenders.append(str(source.relative_to(APP_ROOT.parent)))

    assert offenders == [], (
        "Le contexte tenant doit rester dans app/core/tenancy.py. Fichiers fautifs : "
        + ", ".join(offenders)
    )


def test_tenancy_module_uses_transaction_scope() -> None:
    """Dans `tenancy.py`, le contexte est posé en portée **transaction** (`true`)."""
    content = TENANCY_MODULE.read_text(encoding="utf-8")
    assert "set_config('app.company_id', :company_id, true)" in content
