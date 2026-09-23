"""Environnement Alembic de CoGes.

Les migrations sont exécutées par le rôle **propriétaire** (`coges_owner`), jamais par
`coges_app` et jamais au démarrage de l'API (décision 17). L'URL vient de
l'environnement : aucun identifiant n'est écrit dans le dépôt.

Le DSN provient de `app.core.config.Settings` ; l'autogénération est volontairement
désactivée (voir `target_metadata` plus bas).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Le DSN n'est jamais écrit dans le dépôt : il vient de l'environnement, et c'est
# celui du rôle **propriétaire**. `coges_app` ne migre jamais.
# Un appelant programmatique (la suite pytest, qui migre `coges_test`) peut l'imposer
# en amont ; on ne l'écrase alors pas, pour ne jamais migrer la base de développement.
if not config.get_main_option("sqlalchemy.url", default=None):
    config.set_main_option("sqlalchemy.url", get_settings().require_owner_url())

# Volontairement None : les migrations sont écrites à la main en SQL (§ 8 du Modèle
# de données). L'autogénération comparerait un schéma ORM partiel et proposerait des
# suppressions de tables.
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
