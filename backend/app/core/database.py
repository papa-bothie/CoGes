"""Engine, pool et bases déclaratives SQLAlchemy.

Ce module **ne pose jamais** le contexte tenant : c'est le rôle exclusif de
`app.core.tenancy.tenant_transaction`. Il garantit en revanche qu'une connexion
rendue au pool ne transporte plus d'état de session vers la requête suivante.
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from typing import Any

from sqlalchemy import MetaData, create_engine
from sqlalchemy import event as sa_event
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import text

from app.core.config import get_settings
from app.core.role_guard import install_role_guard

logger = logging.getLogger(__name__)

# Les migrations sont écrites à la main en SQL (§ 8 du Modèle de données) ; cette
# convention ne sert qu'à garder des noms cohérents pour les objets déclarés en ORM.
#: Défaut serveur des colonnes horodatées. Sans lui, l'ORM enverrait NULL au lieu
#: de laisser PostgreSQL appliquer `DEFAULT now()`.
NOW = text("now()")

NAMING_CONVENTION = {
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "uq": "%(table_name)s_%(column_0_N_name)s_uq",
    "ck": "%(table_name)s_%(constraint_name)s_chk",
    "fk": "%(table_name)s_%(column_0_N_name)s_fk",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    """Base déclarative commune à tous les modules."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TenantBase(Base):
    """Toute table tenant-scoped porte `company_id`, barrière 1 du Diagramme 8."""

    __abstract__ = True

    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class IdentifiedTenantBase(TenantBase):
    """Table tenant-scoped dotée d'un identifiant propre (`UNIQUE (company_id, id)`)."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


# Le Diagramme 8 laisse le choix entre `DISCARD ALL` et `RESET`. `RESET ALL` est
# retenu : il neutralise **tous** les paramètres de session, y compris un
# `app.company_id` qu'un `SET` sans `LOCAL` aurait laissé traîner, sans exécuter le
# `DEALLOCATE ALL` de `DISCARD ALL`. Ce dernier invalide les requêtes préparées côté
# serveur alors que psycopg 3 continue de les croire vivantes, ce qui produit
# `prepared statement "_pg3_0" does not exist` à la requête suivante (ADR 0003).
_POOL_RESET_SQL = "RESET ALL"


def _install_pool_reset(engine: Engine) -> None:
    """Neutralise l'état de session au retour d'une connexion dans le pool.

    Le contexte tenant est posé en portée transaction : il meurt au COMMIT, il n'y a
    donc en principe rien à nettoyer. Cette réinitialisation est une barrière de
    plus : même un `SET` de session posé par erreur ne franchit pas le retour au pool.

    À noter : un paramètre personnalisé déjà posé ne revient jamais à NULL, mais à la
    chaîne vide. C'est pourquoi les politiques RLS comparent
    `NULLIF(current_setting('app.company_id', true), '')::uuid` (ADR 0003).
    """

    @sa_event.listens_for(engine, "checkin")
    def _reset_session_state(dbapi_connection: Any, connection_record: Any) -> None:
        try:
            previous_autocommit = dbapi_connection.autocommit
            dbapi_connection.autocommit = True
            try:
                with dbapi_connection.cursor() as cursor:
                    cursor.execute(_POOL_RESET_SQL)
            finally:
                dbapi_connection.autocommit = previous_autocommit
        except Exception:  # pragma: no cover - la connexion est écartée du pool
            logger.warning(
                "La réinitialisation de session a échoué au checkin ; connexion invalidée",
                exc_info=True,
            )
            connection_record.invalidate()


def create_app_engine(
    url: str,
    *,
    echo: bool | None = None,
    pool_size: int | None = None,
    max_overflow: int | None = None,
) -> Engine:
    """Engine borné pour le rôle applicatif, avec réinitialisation au checkin.

    `pool_size` et `max_overflow` sont surchargeables : le test T4 a besoin d'un pool
    d'une seule connexion pour prouver qu'aucun contexte ne survit à une transaction.
    """
    settings = get_settings()
    if settings.db_pooler == "transaction":
        # Derrière un pooler en mode transaction (Neon), le pool est le sien : en
        # garder un second par instance Vercel épuiserait les connexions (risque
        # « épuisement des connexions », Architecture). `prepare_threshold=None` :
        # une requête préparée côté serveur vit sur une connexion physique que la
        # transaction suivante n'aura plus (ADR 0040).
        engine = create_engine(
            url,
            echo=settings.db_echo if echo is None else echo,
            poolclass=NullPool,
            connect_args={"prepare_threshold": None},
            # Aucune valeur liée dans les messages d'erreur, donc ni dans les journaux
            # ni dans Sentry (ADR 0088).
            hide_parameters=True,
            future=True,
        )
    else:
        engine = create_engine(
            url,
            echo=settings.db_echo if echo is None else echo,
            pool_size=settings.db_pool_size if pool_size is None else pool_size,
            max_overflow=settings.db_max_overflow if max_overflow is None else max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            pool_recycle=settings.db_pool_recycle_seconds,
            pool_pre_ping=True,
            hide_parameters=True,
            future=True,
        )
    _install_pool_reset(engine)
    install_role_guard(engine)
    return engine


@lru_cache
def get_engine() -> Engine:
    """Engine unique du processus, sur le DSN du rôle `coges_app`."""
    return create_app_engine(get_settings().require_app_url())


@lru_cache
def get_session_factory() -> sessionmaker[Any]:
    """Fabrique de sessions liée à l'engine du processus."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


# --------------------------------------------------------------- rôles des workers
#
# Deux fabriques supplémentaires, pour les deux rôles de la phase 08 (ADR 0032). Elles
# passent par `create_app_engine`, donc elles héritent du `RESET ALL` au checkin : un
# `app.company_id` ne survit pas davantage sur une connexion de worker que sur une
# connexion d'API. Le contexte tenant reste posé par le seul
# `tenant_transaction(ctx, session_factory=…)`.


@lru_cache
def get_relay_session_factory() -> sessionmaker[Any]:
    """Sessions du relais, en `coges_relay` — trois fonctions, aucune table.

    Pool volontairement minuscule : un seul processus, une seule boucle, une
    transaction à la fois. Ouvrir plus de connexions ne publierait pas plus vite et
    prendrait des places dans le pooler à l'API.
    """
    engine = create_app_engine(get_settings().require_relay_url(), pool_size=1, max_overflow=1)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@lru_cache
def get_analytics_session_factory() -> sessionmaker[Any]:
    """Sessions du job analytique, en `coges_analytics`.

    Seul rôle du projet autorisé à supprimer, et seulement sur `daily_sales_facts` —
    une table intégralement reconstruisible depuis le transactionnel (§ 4.10).
    """
    engine = create_app_engine(get_settings().require_analytics_url())
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
