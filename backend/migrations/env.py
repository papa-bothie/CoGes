"""Environnement Alembic de CoGes.

Les migrations sont exécutées par le rôle **propriétaire** (`coges_owner`), jamais par
`coges_app` et jamais au démarrage de l'API (décision 17). L'URL vient de
l'environnement : aucun identifiant n'est écrit dans le dépôt.

Phase 00 : aucune révision, aucun modèle. `target_metadata` sera branché sur la Base
SQLAlchemy en phase 01.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("COGES_DATABASE_URL_OWNER")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = None


def run_migrations_offline() -> None:
    """Génère le SQL sans connexion (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Applique les migrations sur une connexion réelle."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
