"""The upgrade path for the identity columns.

These columns landed on tables that already had rows in every deployed
database. `create_all()` never alters an existing table, so without the
patch in app/db/session.py the columns are simply absent and every query
naming one fails; and without the backfill they are present but NULL,
which for the phone blind index means a duplicate check that silently
never matches -- worse than not having one, because it looks like it
works.

The backfill cannot be raw SQL. `phone` is AES-GCM encrypted, so hashing
the stored bytes would give every row a different key for the same number.
It has to go through the ORM, and that is why it is a separate step from
the DDL.
"""
import os
import subprocess
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# The demo key conftest sets, so the child process decrypts what we wrote.
TEST_KEY = "c2V2YWthaS10ZXN0LWtleS1ub3QtZm9yLXJlYWwtZGE="


def _old_schema(db_path: Path) -> None:
    """workers and patients exactly as they were before this change."""
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
            status TEXT,
            approved_by TEXT,
            approved_at TIMESTAMP,
            created_at TIMESTAMP
        );
        CREATE TABLE patients (
            patient_id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            village TEXT,
            phone TEXT,
            pregnancy_stage TEXT,
            bp_systolic INTEGER,
            bp_diastolic INTEGER,
            blood_sugar_fasting INTEGER,
            blood_sugar_random INTEGER,
            created_at TIMESTAMP
        );
        INSERT INTO workers VALUES
            ('w-1','Existing ASHA','9111111111','x','hi','SC-PUNE-01','asha','active',NULL,NULL,'2026-01-01'),
            ('w-2','Another ASHA','9111111112','x','hi','SC-PUNE-01','asha','active',NULL,NULL,'2026-01-02'),
            ('w-3','District Admin','9111111113','x','hi',NULL,'admin','active',NULL,NULL,'2026-01-03');
        """
    )
    conn.commit()
    conn.close()


def _run(code: str, db_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env={
            **os.environ,
            "DATABASE_URL": f"sqlite:///{db_path}",
            "PYTHONPATH": str(BACKEND),
            "ENCRYPTION_KEY": TEST_KEY,
            "USE_MOCKS": "true",
        },
        capture_output=True,
        text=True,
    )


def test_an_old_database_gains_the_columns_and_the_values(tmp_path):
    db_path = tmp_path / "old.db"
    _old_schema(db_path)

    # Write a patient through the ORM so her phone is genuinely encrypted,
    # the way a real row is. Done after the DDL patch, before the backfill.
    result = _run(
        """
from app.db.session import init_db, SessionLocal
from app.db.models.patient import Patient
init_db()
db = SessionLocal()
db.add(Patient(patient_id='p-1', worker_id='w-1', name='Kamla Devi',
               village=' wagholi ', phone='+91 98765 12345'))
db.commit(); db.close()
""",
        db_path,
    )
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db_path)
    try:
        worker_cols = {r[1] for r in conn.execute("PRAGMA table_info(workers)")}
        patient_cols = {r[1] for r in conn.execute("PRAGMA table_info(patients)")}
        assert "worker_code" in worker_cols
        assert {"rch_number", "phone_hash", "village_code", "sub_centre_id"} <= patient_cols

        # The older columns are still patched too -- a duplicate "patients"
        # key in the DDL table would silently have dropped them.
        assert {"bp_systolic", "blood_sugar_random"} <= patient_cols
    finally:
        conn.close()

    backfilled = _run("from app.db.session import backfill_identity; backfill_identity()", db_path)
    assert backfilled.returncode == 0, backfilled.stderr

    conn = sqlite3.connect(db_path)
    try:
        codes = dict(conn.execute("SELECT worker_id, worker_code FROM workers"))
        assert all(codes.values()), f"a worker has no code: {codes}"
        assert len(set(codes.values())) == 3, "codes are not unique"
        assert codes["w-1"].startswith("ASHA-PUNE-01-")
        assert codes["w-3"].startswith("ADMIN-")

        village_code, phone_hash, sub_centre = conn.execute(
            "SELECT village_code, phone_hash, sub_centre_id FROM patients WHERE patient_id='p-1'"
        ).fetchone()
        assert village_code == "WAGHOLI", "case and spacing should normalise"
        assert sub_centre == "SC-PUNE-01", "seeded from her worker, once"
        assert phone_hash and "98765" not in phone_hash, "the index must not be the number"
    finally:
        conn.close()


def test_the_backfill_hashes_the_number_not_the_ciphertext(tmp_path):
    """The reason this is ORM work and not an UPDATE statement.

    AES-GCM uses a random nonce, so the same number stored twice is two
    different strings on disk. Hashing those would give two different keys
    for one woman, and the duplicate check would never fire.
    """
    db_path = tmp_path / "hash.db"
    _old_schema(db_path)

    result = _run(
        """
from app.db.session import init_db, SessionLocal, backfill_identity
from app.db.models.patient import Patient
init_db()
db = SessionLocal()
db.add(Patient(patient_id='a', worker_id='w-1', name='One', phone='9876500001'))
db.add(Patient(patient_id='b', worker_id='w-2', name='Two', phone='+91-98765-00001'))
db.commit(); db.close()
backfill_identity()
""",
        db_path,
    )
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db_path)
    try:
        stored = dict(conn.execute("SELECT patient_id, phone FROM patients"))
        assert stored["a"] != stored["b"], "same number, so the ciphertexts must differ"

        hashes = dict(conn.execute("SELECT patient_id, phone_hash FROM patients"))
        assert hashes["a"] == hashes["b"], "same number, so the index must match"
    finally:
        conn.close()


def test_running_the_backfill_twice_changes_nothing(tmp_path):
    """Deploys restart. A backfill that reissued codes on the second run
    would renumber staff whose codes are printed on paperwork."""
    db_path = tmp_path / "twice.db"
    _old_schema(db_path)

    first = _run("from app.db.session import init_db, backfill_identity; init_db(); backfill_identity()", db_path)
    assert first.returncode == 0, first.stderr

    conn = sqlite3.connect(db_path)
    before = dict(conn.execute("SELECT worker_id, worker_code FROM workers"))
    conn.close()

    second = _run("from app.db.session import init_db, backfill_identity; init_db(); backfill_identity()", db_path)
    assert second.returncode == 0, second.stderr

    conn = sqlite3.connect(db_path)
    after = dict(conn.execute("SELECT worker_id, worker_code FROM workers"))
    conn.close()

    assert before == after
