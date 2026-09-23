"""Point d'entrée de l'API CoGes (déployée sur Vercel).

Phase 00 : uniquement la sonde de santé. Aucune connexion base, aucun middleware,
et surtout aucune migration au démarrage (décision 17 de l'architecture V1.1).
"""

from fastapi import APIRouter, FastAPI

app = FastAPI(title="CoGes API", version="0.1.0", docs_url="/api/v1/docs")

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/health", tags=["platform"])
def health() -> dict[str, str]:
    """Sonde de disponibilité du process API."""
    return {"status": "ok"}


app.include_router(api_router)
