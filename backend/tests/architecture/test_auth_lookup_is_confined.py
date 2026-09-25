"""La seule requête sans contexte tenant reste confinée au module Auth.

`auth_lookup_transaction` ouvre une session **sans** poser `app.company_id`. C'est
légitime pour un seul usage — traduire (slug, e-mail) en identité avant toute
authentification — et cette fonction SQL est `SECURITY DEFINER` au périmètre
minimal (ADR 0005). Aucun autre module ne doit s'en servir.

L'analyse porte sur le **code exécutable**, docstrings retirées, comme le fait déjà
`test_tenant_context_is_unique` (ADR 0004). Un module qui cite la fonction pour
expliquer qu'il suit le même patron — le relais de l'outbox, par exemple — documente
une décision ; il ne l'appelle pas. Interdire la mention aurait appris à ne plus
écrire pourquoi.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
AUTH_MODULE = APP_ROOT / "modules" / "auth"

CONTEXTLESS_ENTRYPOINTS = ("auth_lookup_transaction", "auth_lookup")


def _python_sources(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _executable_source(path: Path) -> str:
    """Source du fichier privée de ses docstrings.

    `ast.parse` a déjà jeté les commentaires ; retirer les docstrings laisse
    exactement ce que l'interpréteur exécute.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_only_the_auth_module_queries_without_a_tenant_context() -> None:
    offenders: list[str] = []
    for source in _python_sources(APP_ROOT):
        if AUTH_MODULE in source.parents:
            continue
        content = _executable_source(source)
        if any(entrypoint in content for entrypoint in CONTEXTLESS_ENTRYPOINTS):
            offenders.append(str(source.relative_to(APP_ROOT.parent)))

    assert offenders == [], (
        "La recherche d'identité sans contexte doit rester dans app/modules/auth/. "
        f"Fichiers fautifs : {', '.join(offenders)}"
    )


def test_the_core_never_depends_on_a_module() -> None:
    """Dépendances vers le bas uniquement : `core/` ignore l'existence de `modules/`."""
    offenders: list[str] = []
    for source in _python_sources(APP_ROOT / "core"):
        content = _executable_source(source)
        if "app.modules" in content:
            offenders.append(str(source.relative_to(APP_ROOT.parent)))

    assert offenders == [], f"Le noyau importe un module métier : {', '.join(offenders)}"
