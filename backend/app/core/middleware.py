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
import re
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

import sentry_sdk
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import company_id_var, request_id_var

logger = logging.getLogger("coges.access")

REQUEST_ID_HEADER = "x-request-id"
#: Identifiant fourni par l'appelant, repris seulement s'il est sage : il finit dans les
#: journaux et dans un en-tête de réponse (pas d'injection de ligne ni d'en-tête).
#: `fullmatch` : avec `match`, « $ » accepte un saut de ligne final (ADR 0088).
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,64}")

#: Message de toute erreur imprévue (ADR 0085) : rien d'interne, de quoi rassurer.
SERVER_ERROR_MESSAGE = (
    "Un souci de notre côté. Vos données sont en sécurité. Réessayez dans un instant."
)


def _request_id(request: Request) -> str:
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    return supplied if _SAFE_REQUEST_ID.fullmatch(supplied) else str(uuid4())


def server_error_response(request_id: str) -> JSONResponse:
    """500 au format du projet, avec la référence d'incident et sans aucun détail."""
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "server_error",
                "message": SERVER_ERROR_MESSAGE,
                "details": {},
                "request_id": request_id,
            }
        },
        headers={REQUEST_ID_HEADER: request_id},
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Pose l'identifiant de requête, puis journalise l'appel."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id(request)
        request_id_var.set(request_id)
        company_id_var.set(None)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # Toute erreur imprévue : la trace va au journal et à Sentry, avec la
            # référence ; le client ne reçoit que le corps stable (ADR 0085).
            logger.exception(
                "erreur imprévue",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("request_id", request_id)
                sentry_sdk.capture_exception(exc)
            return server_error_response(request_id)
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
