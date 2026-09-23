"""Point d'entrée de l'API CoGes (déployée sur Vercel).

Aucune migration n'est jouée au démarrage (décision 17) : elles sont une étape de
déploiement. Les routes métier arrivent en phase 02 ; ce module ne câble que la
sonde de santé, la journalisation structurée et le format d'erreur unique.
"""

from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import CogesError
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="CoGes API", version="0.1.0", docs_url="/api/v1/docs")

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/health", tags=["platform"])
def health() -> dict[str, str]:
    """Sonde de disponibilité du process API."""
    return {"status": "ok"}


app.include_router(api_router)


@app.exception_handler(CogesError)
def handle_coges_error(request: Request, exc: Exception) -> JSONResponse:
    """Traduit une erreur métier en `{"error": {"code", "message", "details"}}`.

    Une ressource appartenant à une autre entreprise sort en 404 avec le code
    `not_found` : strictement indiscernable d'une ressource inexistante.
    """
    assert isinstance(exc, CogesError)  # noqa: S101 - garanti par le dispatch FastAPI
    payload: dict[str, Any] = exc.to_payload()
    return JSONResponse(status_code=exc.status_code, content=payload)
