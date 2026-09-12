from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()


def _normalise(url: str) -> str:
    """Make a managed host's DATABASE_URL usable by SQLAlchemy 2.

    Render, Railway, Heroku and Fly all hand out `postgres://user:pw@host/db`.
    SQLAlchemy 1.4 dropped that alias, so 2.x raises

        NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres

    at import time -- before any logging is configured, so what the deploy
    log actually shows is a container that exited instantly with a
    traceback about a plugin. Rewriting it here rather than asking every
    deployer to hand-edit the connection string their platform generated
    (and which it regenerates on database rotation).

    Also pins psycopg2 explicitly: bare `postgresql://` picks whichever
    DBAPI is installed, which differs between a laptop with psycopg3 and an
    image built from requirements.txt.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _normalise(settings.database_url)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# pool_pre_ping: free-tier Postgres closes idle connections, and a pooled
# connection that died while the service was asleep surfaces as a random
# OperationalError on somebody's first request rather than at startup.
# Checking liveness costs one round trip and removes that whole failure.
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=not DATABASE_URL.startswith("sqlite"),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Fine for SQLite dev / demo; use Alembic migrations for real Postgres."""
    from app.db.models import (  # noqa: F401  (import to register with Base.metadata)
        action,
        audit_log,
        hmis_report,
        patient,
        risk_flag,
        sync_queue,
        visit,
        worker,
    )

    Base.metadata.create_all(bind=engine)
    _add_missing_sqlite_columns()


def _add_missing_sqlite_columns() -> None:
    """create_all() only creates missing *tables*, never adds a column to a
    table that already exists -- so a dev.db saved before a model gained a
    new field is stuck without it. Real deployments use Alembic migrations
    (see the docstring above); for the SQLite dev/demo DB, patch in columns
    added after the table already had rows, so an existing local database
    (yours or anyone else's already-seeded copy) picks them up without
    deleting real data."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    added_columns = {
        "audit_log": {"details": "TEXT"},
        "patients": {
            "bp_systolic": "INTEGER",
            "bp_diastolic": "INTEGER",
            "blood_sugar_fasting": "INTEGER",
            "blood_sugar_random": "INTEGER",
        },
    }
    with engine.connect() as conn:
        for table, columns in added_columns.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for column, column_type in columns.items():
                if column not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
        conn.commit()
