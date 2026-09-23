"""Alembic environment for SevakAI.

Deliberately reads its URL and its metadata from the application rather
than from alembic.ini, so there is exactly one definition of each. A
migration run against a different database than the app uses is worse than
no migration at all.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import every model module for its side effect of registering on Base --
# autogenerate compares against Base.metadata, and a model nobody imported
# is a table Alembic will cheerfully propose dropping.
import app.db.models  # noqa: F401
from app.db.session import DATABASE_URL, Base

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER a column in place; batch mode rebuilds the
        # table instead. Harmless on Postgres, essential on the dev DB.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
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
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
