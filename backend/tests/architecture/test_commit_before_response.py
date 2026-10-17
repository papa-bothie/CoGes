"""Toute transaction ouverte par une dépendance est validée **avant** la réponse (ADR 0079).

Une dépendance `yield` de portée `request` (défaut de FastAPI) se ferme après l'envoi
de la réponse : son COMMIT arriverait trop tard, et un COMMIT refusé laisserait au
client un 2xx. Les deux dépendances qui ouvrent `tenant_transaction` doivent donc être
déclarées en portée `function`, sur **chaque** route.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.core.deps import get_platform_session, get_tenant_session
from app.main import app

_TRANSACTIONAL = {get_tenant_session, get_platform_session}


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    for child in dependant.dependencies:
        yield child
        yield from _walk(child)


def _routes(routes: Iterable[Any]) -> Iterator[APIRoute]:
    """Routes de l'application, y compris celles des routeurs inclus (enveloppés)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _routes(nested.routes)


def test_transactional_dependencies_commit_before_the_response() -> None:
    offenders: list[str] = []
    seen = 0
    for route in _routes(app.routes):
        for dependant in _walk(route.dependant):
            if dependant.call in _TRANSACTIONAL:
                seen += 1
                if dependant.scope != "function":
                    offenders.append(f"{sorted(route.methods)} {route.path}")
    assert seen > 0, "aucune route transactionnelle trouvée : le test ne mesure plus rien"
    assert not offenders, f"COMMIT après la réponse sur : {offenders}"
