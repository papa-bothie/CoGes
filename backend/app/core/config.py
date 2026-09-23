"""Configuration de l'application, lue exclusivement depuis l'environnement.

Deux DSN distincts, jamais interchangeables :

* ``database_url_owner`` — rôle propriétaire du schéma, **migrations Alembic uniquement** ;
* ``database_url_app``   — rôle ``coges_app``, ni superuser ni ``BYPASSRLS``, pas de DELETE.

Aucun secret n'est journalisé : les valeurs sensibles sont des ``SecretStr``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> racine
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Paramètres du processus (API ou worker)."""

    model_config = SettingsConfigDict(
        env_prefix="COGES_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Literal["local", "ci", "staging", "production"] = "local"

    # DSN applicatif : requis, c'est le seul que l'API utilise.
    database_url_app: str
    # DSN propriétaire : requis seulement pour migrer, absent en production applicative.
    database_url_owner: str | None = None
    # Bases de test, alimentées par la suite pytest.
    test_database_url_owner: str | None = None
    test_database_url_app: str | None = None

    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: SecretStr = SecretStr("change-me")
    jwt_access_ttl_seconds: int = Field(default=900, ge=60)
    jwt_refresh_ttl_seconds: int = Field(default=1_209_600, ge=3600)

    default_currency: str = Field(default="XOF", pattern="^[A-Z]{3}$")
    default_timezone: str = "Africa/Dakar"

    # Pool borné : une connexion physique ne doit jamais être partagée au milieu
    # d'une transaction (Diagramme 8, étape 4).
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_pool_timeout_seconds: int = Field(default=10, ge=1)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60)
    db_echo: bool = False

    def require_owner_url(self) -> str:
        """DSN propriétaire, ou une erreur explicite si le processus n'a pas le droit de migrer."""
        if not self.database_url_owner:
            raise RuntimeError(
                "COGES_DATABASE_URL_OWNER est absent : ce processus ne peut pas migrer la base."
            )
        return self.database_url_owner


@lru_cache
def get_settings() -> Settings:
    """Instance unique, mise en cache pour tout le processus."""
    return Settings()
