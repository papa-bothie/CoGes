"""Registre des routes protégées par un droit d'offre (ADR 0132).

Comme le registre des permissions : chaque route qui exige un droit d'offre est déclarée
ici, avec ce droit, et **toute** route d'import doit en porter un. Une route d'import
ajoutée sans `require_feature("imports")` fait échouer la CI ; une route protégée
oubliée dans le registre aussi.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.core import plan_features
from app.core.deps import PLAN_FEATURE_ATTRIBUTE
from app.main import app

#: (méthode, chemin) → droit d'offre exigé.
FEATURE_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/imports/{kind}"): "imports",
    ("GET", "/api/v1/imports/{kind}/template"): "imports",
}

#: Les préfixes dont chaque route exige un droit précis.
GUARDED_PREFIXES: dict[str, str] = {"/api/v1/imports": "imports"}


def _features(dependant: Dependant) -> set[str]:
    found: set[str] = set()
    feature = getattr(dependant.call, PLAN_FEATURE_ATTRIBUTE, None)
    if isinstance(feature, str):
        found.add(feature)
    for child in dependant.dependencies:
        found |= _features(child)
    return found


def _routes(routes: Iterable[Any], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Routes avec leur chemin complet, routeurs inclus compris."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _routes(nested.routes, prefix + route.include_context.prefix)


def _protected() -> dict[tuple[str, str], set[str]]:
    protected: dict[tuple[str, str], set[str]] = {}
    for path, route in _routes(app.routes):
        features = _features(route.dependant)
        for method in route.methods:
            if method == "HEAD":
                continue
            protected[(method, path)] = features
    assert protected, "aucune route trouvée : le parcours des routeurs est cassé"
    return protected


def test_every_route_guarded_by_a_plan_feature_is_declared() -> None:
    declared = {key: {value} for key, value in FEATURE_ROUTES.items()}
    observed = {key: value for key, value in _protected().items() if value}
    assert observed == declared


def test_every_import_route_requires_the_imports_feature() -> None:
    missing = [
        f"{method} {path}"
        for (method, path), features in _protected().items()
        for prefix, feature in GUARDED_PREFIXES.items()
        if path.startswith(prefix) and feature not in features
    ]
    assert missing == [], f"routes d'import sans require_feature : {missing}"


def test_the_registry_names_only_catalogue_features() -> None:
    assert set(FEATURE_ROUTES.values()) <= set(plan_features.CATALOGUE)


def test_exports_require_no_plan_feature() -> None:
    """Les exports restent ouverts à toutes les offres (prompt 41)."""
    guarded = [key for key, features in _protected().items() if "/exports" in key[1] and features]
    assert guarded == []
