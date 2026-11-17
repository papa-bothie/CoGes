"""La licence sur site n'est atteignable que par la commande (ADR 0125).

`activate_license` et `license_status` vivent dans la façade de la Plateforme, mais
aucune route, aucune tâche du worker ni aucun autre module ne les nomme : sans la
commande `python -m app.cli activate-license`, CoGes se comporte comme avant. Le test lit
le code source de `app/` ; un appel glissé dans un router ou une tâche le fait échouer.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
LICENSE_FUNCTIONS = {"activate_license", "license_status"}
DEFINED_IN = APP / "modules" / "platform" / "service.py"
CALLED_FROM = APP / "cli.py"


def _names(tree: ast.AST) -> set[str]:
    """Tout nom, attribut ou import qui désigne une des deux fonctions."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in LICENSE_FUNCTIONS:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in LICENSE_FUNCTIONS:
            found.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            found |= {alias.name for alias in node.names if alias.name in LICENSE_FUNCTIONS}
        elif isinstance(node, ast.Constant) and node.value in LICENSE_FUNCTIONS:
            found.add(str(node.value))  # getattr(service, "activate_license")
    return found


def test_the_licence_functions_exist_in_the_platform_facade() -> None:
    tree = ast.parse(DEFINED_IN.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in LICENSE_FUNCTIONS
    }
    assert defined == LICENSE_FUNCTIONS


def test_only_the_command_line_names_them() -> None:
    users = sorted(
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if path not in (DEFINED_IN, CALLED_FROM)
        and _names(ast.parse(path.read_text(encoding="utf-8")))
    )
    assert users == [], f"la licence est appelée hors de la commande : {users}"


def test_the_command_line_calls_both() -> None:
    assert _names(ast.parse(CALLED_FROM.read_text(encoding="utf-8"))) == LICENSE_FUNCTIONS


def test_inside_the_facade_nothing_else_calls_them() -> None:
    """Aucune autre fonction de la façade (donc aucune route qui l'appelle) ne s'en sert."""
    tree = ast.parse(DEFINED_IN.read_text(encoding="utf-8"))
    callers = sorted(
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name not in LICENSE_FUNCTIONS and _names(node)
    )
    assert callers == []
