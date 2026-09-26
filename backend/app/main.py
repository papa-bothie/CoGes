"""Point d'entrée de l'API CoGes (déployée sur Vercel).

Aucune migration n'est jouée au démarrage (décision 17) : elles sont une étape de
déploiement. Ce module se limite au câblage : sonde de santé, journalisation
structurée, format d'erreur unique et montage des routeurs de modules.
"""

from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.errors import CogesError, ValidationFailedError
from app.core.http_security import (
    BodySizeLimitMiddleware,
    IpRateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.observability import init_sentry
from app.modules.analytics.router import router as analytics_router
from app.modules.auth.router import router as auth_router
from app.modules.categories.router import router as categories_router
from app.modules.companies.router import router as companies_router
from app.modules.customers.router import router as customers_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.expenses.router import categories_router as expense_categories_router
from app.modules.expenses.router import router as expenses_router
from app.modules.finance.router import debts_router
from app.modules.finance.router import router as payments_router
from app.modules.importexport.router import exports_router, imports_router
from app.modules.intelligence.router import router as intelligence_router
from app.modules.inventory.router import router as inventory_router
from app.modules.notifications.router import router as notifications_router
from app.modules.products.router import router as products_router
from app.modules.rbac.router import router as rbac_router
from app.modules.sales.router import returns_router
from app.modules.sales.router import router as sales_router
from app.modules.suppliers.router import router as suppliers_router
from app.modules.system.router import router as system_router
from app.modules.users.router import router as users_router

configure_logging()
init_sentry("api")

settings = get_settings()

# La documentation interactive charge Swagger UI depuis un CDN : elle n'est pas servie
# en production. Le contrat reste lisible dans `backend/openapi.json`, versionné.
_docs_enabled = settings.env != "production"
app = FastAPI(
    title="CoGes API",
    version="1.0.0",
    docs_url="/api/v1/docs" if _docs_enabled else None,
    redoc_url=None,
    openapi_url="/api/v1/openapi.json" if _docs_enabled else None,
)
# Starlette enveloppe dans l'ordre inverse d'ajout : le dernier ajouté est le plus
# extérieur. De l'extérieur vers l'intérieur : en-têtes de sécurité (sur toute
# réponse, y compris un 413 ou un 429), CORS (un refus doit rester lisible par le
# navigateur), taille du corps, débit par IP, puis journalisation.
app.add_middleware(RequestContextMiddleware)
app.add_middleware(IpRateLimitMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Le cookie de rafraîchissement est `httpOnly` (ADR 0006) : le navigateur ne
    # l'envoie qu'avec `credentials: 'include'`, donc sur une origine nommée.
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
    expose_headers=["X-Request-Id", "Retry-After", "Content-Disposition"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware)

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
api_router.include_router(sales_router)
api_router.include_router(returns_router)
# Bande D : Finance porte les écritures d'argent et la vie des dettes ; Expenses
# ne dépend que d'elle.
api_router.include_router(payments_router)
api_router.include_router(debts_router)
api_router.include_router(expense_categories_router)
api_router.include_router(expenses_router)
# Bande E : restitution. Elle lit les bandes du dessous par leurs façades, et rien
# ne la lit — seul sens que l'ordre des dépendances autorise. Analytics possède la
# seule table de la bande, `daily_sales_facts`, qui est une projection reconstruisible.
api_router.include_router(analytics_router)
api_router.include_router(notifications_router)
# CoGes Intelligence : lecture seule de résultats déjà calculés par le worker
# (décision 11). Aucune route n'infère ; seule `PATCH /insights/{id}` écrit un statut.
api_router.include_router(intelligence_router)
api_router.include_router(dashboard_router)
# Bande E : Import/Export écrit les référentiels par leurs façades et lit les ventes ;
# rien ne le lit. Les exports volumineux sont produits par le worker (ADR 0041).
api_router.include_router(imports_router)
api_router.include_router(exports_router)
# Hors commerce : santé du chemin asynchrone, gérant seul.
api_router.include_router(system_router)

app.include_router(api_router)


@app.exception_handler(CogesError)
def handle_coges_error(request: Request, exc: Exception) -> JSONResponse:
    """Traduit une erreur métier en `{"error": {"code", "message", "details"}}`.

    Une ressource appartenant à une autre entreprise sort en 404 avec le code
    `not_found` : strictement indiscernable d'une ressource inexistante.
    """
    assert isinstance(exc, CogesError)  # noqa: S101 - garanti par le dispatch FastAPI
    payload: dict[str, Any] = exc.to_payload()
    return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)


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
