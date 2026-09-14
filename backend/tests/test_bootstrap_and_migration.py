"""The first admin, and the column that gates every login.

Two things that only ever run once, and are therefore the two things
nobody notices are broken until the day they matter.
"""
import subprocess
import sys
import sqlite3
from pathlib import Path

from app.db.models.worker import Worker
from app.db.session import SessionLocal

BACKEND = Path(__file__).resolve().parent.parent


def _run_bootstrap(env_extra: dict, db_path: Path) -> subprocess.CompletedProcess:
    import os

    env = {
        **os.environ,
        # Its own database file, so this never touches the suite's.
        "DATABASE_URL": f"sqlite:///{db_path}",
        "PYTHONPATH": str(BACKEND),
        **env_extra,
    }
    return subprocess.run(
        [sys.executable, "scripts/bootstrap_admin.py"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )


def test_bootstrap_creates_one_admin_then_refuses_forever(tmp_path):
    """A bootstrap that can be run twice is a back door: anyone who can
    reach the environment mints themselves an admin and reads every patient
    record in the district."""
    db_path = tmp_path / "bootstrap.db"
    env = {
        "BOOTSTRAP_ADMIN_NAME": "Block Admin",
        "BOOTSTRAP_ADMIN_PHONE": "9876500011",
        "BOOTSTRAP_ADMIN_PIN": "8317",
    }

    first = _run_bootstrap(env, db_path)
    assert first.returncode == 0, first.stderr
    assert "Created admin" in first.stdout

    second = _run_bootstrap({**env, "BOOTSTRAP_ADMIN_PHONE": "9876500012"}, db_path)
    assert second.returncode == 1
    assert "already exists" in second.stderr


def test_bootstrap_refuses_a_guessable_pin(tmp_path):
    """On the one account that can read every patient record in the
    district, and the PIN a tired person reaches for first."""
    for pin in ("1234", "0000", "1111"):
        result = _run_bootstrap(
            {
                "BOOTSTRAP_ADMIN_NAME": "Block Admin",
                "BOOTSTRAP_ADMIN_PHONE": "9876500013",
                "BOOTSTRAP_ADMIN_PIN": pin,
            },
            tmp_path / f"pin_{pin}.db",
        )
        assert result.returncode == 1, pin
        assert "PIN" in result.stderr


def test_bootstrap_refuses_an_incomplete_environment(tmp_path):
    result = _run_bootstrap(
        {"BOOTSTRAP_ADMIN_NAME": "Block Admin", "BOOTSTRAP_ADMIN_PIN": "8317"},
        tmp_path / "incomplete.db",
    )
    assert result.returncode == 1
    assert "PHONE" in result.stderr


def test_an_old_database_gains_the_status_column_as_active(tmp_path):
    """The real upgrade path, and the one that could not be undone.

    `status` arrived on a workers table that already had rows in every
    deployed database. create_all() never alters an existing table, so
    without the patch in app/db/session.py those rows have no status at
    all -- and login() refuses anything that is not exactly "active".
    Every worker in the district, including the only admin, locked out by
    a column nobody backfilled.
    """
    db_path = tmp_path / "old_schema.db"
    # A workers table exactly as it was before this change.
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE workers (
            worker_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            pin_hash TEXT NOT NULL,
            language_pref TEXT,
            sub_centre_id TEXT,
            role TEXT,
            created_at TIMESTAMP
        );
        INSERT INTO workers VALUES
            ('w-old-1', 'Existing ASHA', '9111111111', 'x', 'hi', 'SC-1', 'asha', '2026-01-01'),
            ('w-old-2', 'Existing Admin', '9111111112', 'x', 'hi', NULL, 'admin', '2026-01-01');
        """
    )
    conn.commit()
    conn.close()

    # Bring that database up to the current schema the way a deploy does.
    import os

    result = subprocess.run(
        [sys.executable, "-c", "from app.db.session import init_db; init_db()"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db_path}", "PYTHONPATH": str(BACKEND)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(workers)")}
        assert {"status", "approved_by", "approved_at"} <= columns

        rows = dict(conn.execute("SELECT worker_id, status FROM workers"))
        # Both, and "active" -- not NULL, not "pending".
        assert rows == {"w-old-1": "active", "w-old-2": "active"}
    finally:
        conn.close()


def test_running_the_upgrade_twice_changes_nothing(tmp_path):
    """Deploys restart. A patch that throws the second time it runs is a
    service that comes up once and then will not."""
    import os

    db_path = tmp_path / "twice.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path}", "PYTHONPATH": str(BACKEND)}
    for attempt in range(2):
        result = subprocess.run(
            [sys.executable, "-c", "from app.db.session import init_db; init_db()"],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"attempt {attempt + 1}: {result.stderr}"


def test_the_seeded_demo_accounts_are_active():
    """They are what every demo signs in with. A seeder that produced
    pending accounts would look identical until somebody tried to log in."""
    db = SessionLocal()
    try:
        demo = db.query(Worker).filter(Worker.phone == "9999999999").first()
        assert demo is not None
        assert demo.status == "active"
    finally:
        db.close()
