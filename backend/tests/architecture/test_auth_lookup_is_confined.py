"""La seule requête sans contexte tenant reste confinée au module Auth.

`auth_lookup_transaction` ouvre une session **sans** poser `app.company_id`. C'est
légitime pour un seul usage — traduire (slug, e-mail) en identité avant toute
authentification — et cette fonction SQL est `SECURITY DEFINER` au périmètre
minimal (ADR 0005). Aucun autre module ne doit s'en servir.
"""

from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
AUTH_MODULE = APP_ROOT / "modules" / "auth"

CONTEXTLESS_ENTRYPOINTS = ("auth_lookup_transaction", "auth_lookup")


def _python_sources(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_only_the_auth_module_queries_without_a_tenant_context() -> None:
    offenders: list[str] = []
    for source in _python_sources(APP_ROOT):
        if AUTH_MODULE in source.parents:
            continue
        content = source.read_text(encoding="utf-8")
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
        content = source.read_text(encoding="utf-8")
        if "app.modules" in content:
            offenders.append(str(source.relative_to(APP_ROOT.parent)))

    assert offenders == [], f"Le noyau importe un module métier : {', '.join(offenders)}"
