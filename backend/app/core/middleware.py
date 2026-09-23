"""Middleware de journalisation structurée.

Un middleware s'exécute dans le **contexte de la requête**, du début à la fin : c'est
le seul endroit où poser des `ContextVar` sans risque. Une dépendance FastAPI
synchrone, elle, est mise en place et refermée dans deux contextes différents.

Chaque requête produit une ligne JSON : identifiant de corrélation, méthode, chemin,
statut, durée et `company_id` quand l'utilisateur est authentifié. Jamais de jeton,
jamais de mot de passe, jamais de cookie.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import company_id_var, request_id_var

logger = logging.getLogger("coges.access")

REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Pose l'identifiant de requête, puis journalise l'appel."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        request_id_var.set(request_id)
        company_id_var.set(None)

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        tenant = getattr(request.state, "tenant", None)
        company_id = str(tenant.company_id) if tenant is not None else None
        company_id_var.set(company_id)

        logger.info(
            "requête traitée",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
