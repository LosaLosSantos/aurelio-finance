"""Alembic environment: wires migrations to the app's models and database.

Instead of hardcoding a connection string in alembic.ini, we import the app's
own configuration (app.database) so migrations always target the same database
the app uses (DATABASE_URL env var, or backend/data.db by default), and
autogenerate diffs against the real ORM metadata.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Importing app.models registers every table on Base.metadata, which is what
# `alembic revision --autogenerate` compares the database against.
import app.models  # noqa: F401
from app.database import DATABASE_URL, Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# The app decides the URL (env var or default file); alembic.ini stays dummy.
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging, unless the caller says not to.
# The app runs migrations from uvicorn's startup (app.database.init_db), and
# fileConfig's default switches off every logger that already exists, uvicorn's
# included: a migration that failed at startup exited without a word, and
# every start went quiet after its fourth line. The app sets
# `configure_logger` to False; the `alembic` command line sets nothing and
# keeps this logging as it always had.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER columns in place; batch mode rebuilds the table.
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (against a live connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
