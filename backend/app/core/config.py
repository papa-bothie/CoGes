"""Configuration de l'application, lue exclusivement depuis l'environnement.

Quatre DSN distincts, jamais interchangeables :

* ``database_url_owner``     — rôle propriétaire du schéma, **migrations Alembic uniquement** ;
* ``database_url_app``       — rôle ``coges_app``, ni superuser ni ``BYPASSRLS``, pas de DELETE ;
* ``database_url_relay``     — rôle ``coges_relay``, aucun privilège de table : il n'appelle que
  trois fonctions ``SECURITY DEFINER`` (ADR 0032) ;
* ``database_url_analytics`` — rôle ``coges_analytics``, seul autorisé à ``DELETE``, et seulement
  sur des projections reconstruisibles.

Aucun secret n'est journalisé : les valeurs sensibles sont des ``SecretStr``.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> racine
REPO_ROOT = Path(__file__).resolve().parents[3]

#: HMAC-SHA256 : une clé plus courte que sa sortie affaiblit la signature.
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Paramètres du processus (API ou worker)."""

    model_config = SettingsConfigDict(
        env_prefix="COGES_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        # Un secret collé dans GitHub ou Vercel garde souvent son retour à la ligne :
        # un DSN terminé par « \n » ferait échouer la connexion de façon obscure.
        str_strip_whitespace=True,
    )

    env: Literal["local", "ci", "staging", "production"] = "local"

    # DSN applicatif : le seul que l'API utilise. Absent du seul relais, qui ne tourne
    # que sous `coges_relay` (ADR 0032) : `require_app_url` échoue alors à l'usage.
    database_url_app: str | None = None
    # DSN propriétaire : requis seulement pour migrer, absent en production applicative.
    database_url_owner: str | None = None
    # DSN des workers : absents d'un déploiement API-seule, requis dans l'image worker.
    database_url_relay: str | None = None
    database_url_analytics: str | None = None
    # Bases de test, alimentées par la suite pytest.
    test_database_url_owner: str | None = None
    test_database_url_app: str | None = None
    test_database_url_relay: str | None = None
    test_database_url_analytics: str | None = None

    redis_url: str = "redis://localhost:6379/0"

    # --- Relais de l'outbox (ADR 0032) ---
    # Lot réclamé par passage. Trop grand, une panne de Redis consomme une tentative
    # sur trop d'événements à la fois ; trop petit, la latence monte.
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)
    # Pause quand la file est vide. Le relais n'est pas réveillé par NOTIFY : il
    # sonde, et c'est ce qui le rend insensible à une déconnexion (ADR 0032).
    outbox_poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    # Plafond de tentatives. `business_events` porte un CHECK `attempts <= 10` : ce
    # réglage ne peut pas le dépasser, il peut seulement être plus prudent.
    outbox_max_attempts: int = Field(default=10, ge=1, le=10)
    # Plafond du back-off exponentiel après un échec de publication.
    outbox_backoff_max_seconds: float = Field(default=60.0, gt=0, le=600)
    # Plafond de l'espacement des passages quand la file est vide (ADR 0040). Égal à
    # l'intervalle de sondage par défaut : aucun espacement. 600 en préproduction sur
    # l'offre gratuite de Neon, pour que la base s'endorme entre deux passages.
    outbox_idle_max_seconds: float = Field(default=1.0, gt=0, le=3600)

    # --- Restitution ---
    # Cache court par tenant, invalidé par événement (décision 14). Jamais sur le
    # chemin critique : une panne de Redis fait recalculer, pas échouer.
    dashboard_cache_ttl_seconds: int = Field(default=60, ge=0, le=3600)
    # Fenêtre de déduplication des alertes : un même fait ne réveille pas deux fois
    # la même personne dans la journée.
    notification_dedupe_hours: int = Field(default=24, ge=1, le=168)

    # --- CoGes Intelligence (ADR 0035) ---
    # Artefacts de modèle, hors base (§ 6) : volume du conteneur worker. L'API ne le
    # lit jamais — elle ne sert que `forecasts` et `insights`.
    ml_artifacts_dir: Path = Path("/var/lib/coges/ml")

    # 32 octets minimum : en deçà, PyJWT avertit que la clé est trop courte pour
    # HMAC-SHA256 (RFC 7518 § 3.2).
    jwt_secret: SecretStr = SecretStr("change-me-" + "0" * 32)
    jwt_access_ttl_seconds: int = Field(default=900, ge=60)
    # 7 jours (ADR 0006). Le cookie de rafraîchissement lit la même valeur.
    jwt_refresh_ttl_seconds: int = Field(default=604_800, ge=3600)

    default_currency: str = Field(default="XOF", pattern="^[A-Z]{3}$")
    default_timezone: str = "Africa/Dakar"

    # Pool borné : une connexion physique ne doit jamais être partagée au milieu
    # d'une transaction (Diagramme 8, étape 4).
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_pool_timeout_seconds: int = Field(default=10, ge=1)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60)
    db_echo: bool = False
    # Pooler externe en mode transaction (Neon, Diagramme 8 étape 4). Le pool local
    # disparaît (`NullPool`) et psycopg ne prépare plus de requêtes côté serveur :
    # une requête préparée ne survit pas au changement de connexion physique.
    db_pooler: Literal["none", "transaction"] = "none"

    # --- Sécurité HTTP (ADR 0042) ---
    # Origines autorisées à appeler l'API depuis un navigateur, séparées par des
    # virgules. Vide : aucune (CORS fermé).
    cors_origins: str = ""
    # Corps de requête maximal, en octets. Les imports ont leur propre plafond, sous
    # la limite de 4,5 Mo des fonctions Vercel.
    max_body_bytes: int = Field(default=1_048_576, ge=1024)
    max_import_bytes: int = Field(default=4_194_304, ge=1024, le=4_500_000)
    # Limitation de débit par minute (décision 16). 0 désactive le compteur.
    rate_limit_ip_per_minute: int = Field(default=300, ge=0)
    rate_limit_tenant_per_minute: int = Field(default=1200, ge=0)
    rate_limit_login_per_minute: int = Field(default=10, ge=0)

    # Derrière Vercel, l'adresse du client arrive dans `X-Forwarded-For`, que la
    # plate-forme réécrit. En local, l'en-tête viendrait du client : on l'ignore.
    trust_proxy_headers: bool = False

    # --- Observabilité ---
    # DSN Sentry : absent, Sentry reste inactif (développement, CI).
    sentry_dsn: SecretStr | None = None
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0, le=1)

    # --- Surveillance des workers (ADR 0077) ---
    # Jeton de `GET /system/workers`. Absent : la route répond 404, comme si elle
    # n'existait pas.
    ops_token: SecretStr | None = None
    # Retard toléré du plus vieil événement en attente. 600 s en production ; 900 s en
    # préproduction, où le relais espace ses passages jusqu'à 600 s (ADR 0040).
    ops_outbox_max_lag_seconds: int = Field(default=600, gt=0, le=86400)
    # Pings « homme mort » : `{"nom de tâche": "url"}` en JSON. Absent ou vide : aucun
    # ping (le compose des workers transmet une chaîne vide quand rien n'est configuré).
    job_ping_urls: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)

    # --- Heure figée (ADR 0065) ---
    # Pour comparer le front à la maquette v2 au pixel près : « aujourd'hui » devient ce
    # moment (`2026-10-06T10:45:00+00:00`) dans les lectures métier (`app/core/clock.py`).
    # Seulement en `local` et en `ci` : refusé au démarrage partout ailleurs.
    frozen_now: AwareDatetime | None = None

    @field_validator("jwt_secret")
    @classmethod
    def _secret_is_long_enough(cls, value: SecretStr) -> SecretStr:
        """Refuse au démarrage une clé de signature trop courte."""
        if len(value.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"COGES_JWT_SECRET doit faire au moins {MIN_JWT_SECRET_LENGTH} caractères."
            )
        return value

    @field_validator("job_ping_urls", mode="before")
    @classmethod
    def _ping_urls_from_json(cls, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value) if value.strip() else {}
        return value

    @field_validator("job_ping_urls")
    @classmethod
    def _ping_urls_are_http(cls, value: dict[str, str]) -> dict[str, str]:
        """Refuse au démarrage une URL de ping qui ne serait pas HTTP(S)."""
        for job, url in value.items():
            if not url.startswith(("https://", "http://")):
                raise ValueError(f"COGES_JOB_PING_URLS : l'URL de « {job} » doit être HTTP(S).")
        return value

    @model_validator(mode="after")
    def _frozen_clock_only_in_local_and_ci(self) -> "Settings":
        """Refuse au démarrage une heure figée hors `local` et `ci` (ADR 0065)."""
        if self.frozen_now is not None and self.env not in ("local", "ci"):
            raise ValueError(
                "COGES_FROZEN_NOW n'est accepté qu'en local et en CI "
                f"(COGES_ENV vaut « {self.env} »)."
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        """Origines CORS, sans espaces ni entrées vides."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def require_app_url(self) -> str:
        """DSN de `coges_app`, ou une erreur explicite si le processus ne l'a pas reçu."""
        if not self.database_url_app:
            raise RuntimeError(
                "COGES_DATABASE_URL_APP est absent : ce processus ne peut pas ouvrir de "
                "transaction applicative."
            )
        return self.database_url_app

    def require_owner_url(self) -> str:
        """DSN propriétaire, ou une erreur explicite si le processus n'a pas le droit de migrer."""
        if not self.database_url_owner:
            raise RuntimeError(
                "COGES_DATABASE_URL_OWNER est absent : ce processus ne peut pas migrer la base."
            )
        return self.database_url_owner

    def require_relay_url(self) -> str:
        """DSN du relais, ou une erreur explicite : jamais de repli sur `coges_app`.

        Se rabattre silencieusement sur le rôle applicatif ferait échouer le relais
        sur la RLS, un lot à la fois, sans que la cause soit lisible.
        """
        if not self.database_url_relay:
            raise RuntimeError(
                "COGES_DATABASE_URL_RELAY est absent : ce processus ne peut pas relayer l'outbox."
            )
        return self.database_url_relay

    def require_analytics_url(self) -> str:
        """DSN du rôle analytique, ou une erreur explicite.

        `coges_app` n'a pas le droit DELETE : sans ce DSN, la purge des faits devenus
        vides échouerait au lieu de laisser un agrégat faussement complet.
        """
        if not self.database_url_analytics:
            raise RuntimeError(
                "COGES_DATABASE_URL_ANALYTICS est absent : ce processus ne peut pas "
                "reconstruire les agrégats."
            )
        return self.database_url_analytics


@lru_cache
def get_settings() -> Settings:
    """Instance unique, mise en cache pour tout le processus."""
    return Settings()
