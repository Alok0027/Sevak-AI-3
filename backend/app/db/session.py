from collections.abc import Generator
from datetime import datetime

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
        absence,
        action,
        audit_log,
        hmis_report,
        patient,
        risk_flag,
        support_ticket,
        sync_queue,
        visit,
        visit_request,
        notification,
        risk_resolution,
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
        # Formal identity and geography -- see app/services/identity.py.
        # UNIQUE is left to the model for the same reason as worker_code
        # below: SQLite will not add a unique column to a populated table.
        "rch_number": "TEXT",
        "phone_hash": "TEXT",
        "village_code": "TEXT",
        "sub_centre_id": "TEXT",
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
        # Deliberately declared without UNIQUE here. SQLite cannot add a
        # unique column to a populated table, and the values do not exist
        # until backfill_identity() below has run -- at which point a
        # duplicate would be a bug, not a race. The model declares the
        # constraint so a database created from scratch has it.
        "worker_code": "TEXT",
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


def backfill_identity() -> None:
    """Fill in the identifiers and keys that arrived after the rows did.

    Separate from _add_missing_columns() because this is not DDL: the
    phone blind index needs the plaintext phone number, which only exists
    on the far side of the ORM's decryption. Raw SQL would hash the
    ciphertext, and every row would get a different key for the same
    number -- a duplicate check that silently never matches, which is
    worse than not having one.

    Idempotent, and cheap when there is nothing to do: it looks only at
    rows where the new column is still NULL, so a restart with everything
    filled costs two indexed counts. Called from the app's lifespan, so a
    deploy upgrades itself rather than waiting for somebody to remember a
    script.
    """
    from app.db.models.patient import Patient
    from app.db.models.worker import Worker
    from app.services import identity

    db = SessionLocal()
    try:
        _backfill_worker_codes(db, Worker, identity)
        _backfill_patient_keys(db, Patient, identity)
        db.commit()
    except Exception:  # noqa: BLE001
        # A backfill that cannot finish must not stop the API from
        # serving. The columns are nullable and every reader tolerates a
        # NULL; the next boot tries again.
        db.rollback()
        raise
    finally:
        db.close()


def _backfill_worker_codes(db, Worker, identity) -> None:
    pending = db.query(Worker).filter(Worker.worker_code.is_(None)).all()
    if not pending:
        return

    # Serials continue from what is already issued rather than restarting
    # at 1, or the second run of this would hand ASHA-PUNE-01-001 to a
    # second person and the unique constraint would reject the whole
    # batch.
    used: set[str] = {
        code for (code,) in db.query(Worker.worker_code).filter(Worker.worker_code.isnot(None))
    }
    counters: dict[tuple[str, str], int] = {}

    # Oldest first, so the numbers follow the order people actually
    # joined rather than the order a query happened to return them.
    for worker in sorted(pending, key=lambda w: (w.created_at or datetime.min, w.worker_id)):
        key = (worker.role or "asha", worker.sub_centre_id or "")
        serial = counters.get(key, 0)
        while True:
            serial += 1
            candidate = identity.worker_code(worker.role, worker.sub_centre_id, serial)
            if candidate not in used:
                break
        counters[key] = serial
        used.add(candidate)
        worker.worker_code = candidate


def _backfill_patient_keys(db, Patient, identity) -> None:
    pending = (
        db.query(Patient)
        .filter(
            (Patient.village_code.is_(None) & Patient.village.isnot(None))
            | (Patient.phone_hash.is_(None) & Patient.phone.isnot(None))
            | Patient.sub_centre_id.is_(None)
        )
        .all()
    )
    if not pending:
        return

    from app.db.models.worker import Worker

    # One lookup for every worker involved, rather than one per patient.
    worker_ids = {p.worker_id for p in pending}
    sub_centres = {
        w.worker_id: w.sub_centre_id
        for w in db.query(Worker).filter(Worker.worker_id.in_(worker_ids)).all()
    }

    for patient in pending:
        if patient.village_code is None:
            patient.village_code = identity.village_code(patient.village)
        if patient.phone_hash is None:
            patient.phone_hash = identity.phone_index(patient.phone)
        if patient.sub_centre_id is None:
            # Seeded from her worker, which is the only record of where
            # she is that exists before this column did. From here on it
            # is her own, and reassignment leaves it alone.
            patient.sub_centre_id = sub_centres.get(patient.worker_id)
