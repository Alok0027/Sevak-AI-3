from collections.abc import Generator

from sqlalchemy import create_engine, inspect
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
        support_ticket,
        sync_queue,
        visit,
        worker,
    )

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


# Columns added to a model after its table already existed somewhere.
#
# Types are written in the SQL both SQLite and Postgres accept, because the
# same list has to patch a developer's dev.db and a deployed Postgres.
# TEXT and INTEGER are fine in both; anything needing a dialect-specific
# type is the point at which this stops being adequate and Alembic starts.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "audit_log": {"details": "TEXT"},
    "patients": {
        "bp_systolic": "INTEGER",
        "bp_diastolic": "INTEGER",
        "blood_sugar_fasting": "INTEGER",
        "blood_sugar_random": "INTEGER",
    },
    # Registration + approval. The DEFAULT matters as much as the column:
    # it is what every worker row already in the database gets, and without
    # it every existing account -- including the only admin -- would land
    # on NULL, fail the "is this account active" check in login(), and lock
    # the whole deployment out at the exact moment this code shipped.
    "workers": {
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "approved_by": "TEXT",
        "approved_at": "TIMESTAMP",
    },
}


def _add_missing_columns() -> None:
    """Patch in columns added after a table already had rows.

    create_all() creates missing *tables* and never touches an existing
    one, so a database saved before a model gained a field is stuck without
    it -- and on a deployed Postgres that means every query naming the new
    column fails until somebody runs DDL by hand.

    This used to be SQLite-only, which was fine while the only database
    that mattered was a developer's dev.db. It is not fine now: the
    deployed Postgres has the same tables, created by the same create_all()
    on an earlier version of these models, and it needs the same patch.

    Real deployments should use Alembic migrations (see the module
    docstring). This is the stopgap that keeps a demo deployment upgrading
    cleanly, and it is deliberately narrow: additive columns only, never a
    rename, a type change or a drop.
    """
    is_sqlite = DATABASE_URL.startswith("sqlite")
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.connect() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all() just made it, with every column
            existing = {c["name"] for c in inspector.get_columns(table)}
            for column, ddl in columns.items():
                if column in existing:
                    continue
                # SQLite has no ADD COLUMN IF NOT EXISTS, which is why the
                # membership check above exists rather than relying on it.
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        conn.commit()

    # SQLite fills existing rows from the DEFAULT on ADD COLUMN, and so
    # does Postgres (11+). Older Postgres does not, so make it true either
    # way rather than depending on the server version a host happens to
    # give you -- a NULL status is an account that cannot log in.
    if not is_sqlite:
        with engine.connect() as conn:
            conn.exec_driver_sql("UPDATE workers SET status = 'active' WHERE status IS NULL")
            conn.commit()
