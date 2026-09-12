from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
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
    if not settings.database_url.startswith("sqlite"):
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
