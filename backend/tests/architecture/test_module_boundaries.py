"""Frontières entre modules métier (décision 01).

Un module de `app/modules/` n'importe jamais le `repository` ni les `models` d'un autre
module : il passe par la façade `service`. Le test analyse les imports en AST, donc il
attrape aussi bien `from app.modules.x.repository import ...` que `import
app.modules.x.models`.

Phase 00 : `app/modules/` est vide, le test passe à vide. Il devient actif dès le
premier module métier, sans rien changer ici.
"""

from __future__ import annotations

import ast
from pathlib import Path

MODULES_ROOT = Path(__file__).resolve().parents[2] / "app" / "modules"
PRIVATE_SUBMODULES = ("repository", "models")


def _imported_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
            names.append(node.module)
    return names


def _module_name(path: Path) -> str:
    return path.relative_to(MODULES_ROOT).parts[0]


def test_no_module_imports_another_module_repository_or_models() -> None:
    violations: list[str] = []

    for source in sorted(MODULES_ROOT.rglob("*.py")):
        owner = _module_name(source)
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

        for imported in _imported_names(tree):
            if not imported.startswith("app.modules."):
                continue
            parts = imported.split(".")
            if len(parts) < 4:
                continue
            target, submodule = parts[2], parts[3]
            if target != owner and submodule in PRIVATE_SUBMODULES:
                violations.append(f"{source.relative_to(MODULES_ROOT.parents[1])} -> {imported}")

    assert not violations, "Imports interdits entre modules :\n" + "\n".join(violations)
