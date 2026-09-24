"""Point d'entrée de l'API CoGes (déployée sur Vercel).

Aucune migration n'est jouée au démarrage (décision 17) : elles sont une étape de
déploiement. Ce module se limite au câblage : sonde de santé, journalisation
structurée, format d'erreur unique et montage des routeurs de modules.
"""

from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import CogesError, ValidationFailedError
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.modules.auth.router import router as auth_router
from app.modules.categories.router import router as categories_router
from app.modules.companies.router import router as companies_router
from app.modules.customers.router import router as customers_router
from app.modules.inventory.router import router as inventory_router
from app.modules.products.router import router as products_router
from app.modules.rbac.router import router as rbac_router
from app.modules.sales.router import router as sales_router
from app.modules.suppliers.router import router as suppliers_router
from app.modules.users.router import router as users_router

configure_logging()

app = FastAPI(title="CoGes API", version="0.1.0", docs_url="/api/v1/docs")
app.add_middleware(RequestContextMiddleware)

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/health", tags=["platform"])
def health() -> dict[str, str]:
    """Sonde de disponibilité du process API."""
    return {"status": "ok"}


api_router.include_router(auth_router)
api_router.include_router(companies_router)
api_router.include_router(users_router)
api_router.include_router(rbac_router)
api_router.include_router(categories_router)
api_router.include_router(products_router)
api_router.include_router(customers_router)
api_router.include_router(suppliers_router)
# Bande C : Inventory lit Products, jamais l'inverse (ADR 0012).
api_router.include_router(inventory_router)
# Bande D : Sales lit tout ce qui précède par leurs façades ; rien ne le lit.
# Finance n'a pas de router en V1-phase 05 : elle n'est appelée que par Sales.
api_router.include_router(sales_router)

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


@app.exception_handler(RequestValidationError)
def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Normalise les erreurs de validation Pydantic au format du projet.

    Sans ce gestionnaire, FastAPI renverrait `{"detail": [...]}`, qui n'est pas le
    contrat d'erreur de CoGes.
    """
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    fields = [
        {
            "field": ".".join(str(part) for part in error["loc"][1:]),
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    error = ValidationFailedError(details={"fields": fields})
    return JSONResponse(status_code=error.status_code, content=error.to_payload())


#: Codes métier stables associés aux statuts HTTP produits par Starlette
#: (route inconnue, méthode non autorisée...).
_HTTP_ERROR_CODES = {
    404: "not_found",
    405: "method_not_allowed",
    422: "validation_failed",
    429: "rate_limited",
}


@app.exception_handler(StarletteHTTPException)
def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """Donne le format d'erreur du projet aux exceptions HTTP de la plate-forme."""
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": str(exc.detail), "details": {}}},
    )
