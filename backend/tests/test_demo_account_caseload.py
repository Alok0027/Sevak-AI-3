"""The demo login must open on a real working day.

The seeder produced 161 patients and 801 visits, and handed every one of
them to a generated ASHA with a random phone number and PIN 0000. The demo
account -- Sunita Sharma, 9999999999, the only login written down anywhere
-- got a single patient and no visits at all. So the app opened on
"1 patient, 0 visits, nothing due today" against a database that was full.

Nothing was broken and nothing was missing. The data was simply under
accounts nobody could sign in to. These tests keep the demo account's own
caseload wired in, and keep the seeder safe to run twice.
"""
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.db.session import SessionLocal
from scripts.seed_synthetic_data import (
    DEMO_WORKER_PHONE,
    seed_demo_fixtures,
    seed_demo_worker_caseload,
)


def _demo_worker(db) -> Worker:
    return db.query(Worker).filter(Worker.phone == DEMO_WORKER_PHONE).first()


def test_demo_worker_has_patients_and_visits():
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
        seed_demo_worker_caseload(db, patients_per_worker=8, months_history=3)

        worker = _demo_worker(db)
        assert worker is not None

        patients = db.query(Patient).filter(Patient.worker_id == worker.worker_id).count()
        visits = db.query(Visit).filter(Visit.worker_id == worker.worker_id).count()

        # Meera plus the caseload. The exact number of visits is random, but
        # "some" is the whole point -- zero is the bug.
        assert patients > 1
        assert visits > 0
    finally:
        db.close()


def test_running_the_seeder_twice_does_not_double_the_caseload():
    """The seeder appends. If this guard goes, a second run gives the demo
    ASHA sixteen patients and two overlapping histories, which is exactly
    how the deployed database ended up at 3.5x the local one."""
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
        seed_demo_worker_caseload(db, patients_per_worker=8, months_history=3)
        worker = _demo_worker(db)
        before = db.query(Patient).filter(Patient.worker_id == worker.worker_id).count()

        seed_demo_worker_caseload(db, patients_per_worker=8, months_history=3)

        after = db.query(Patient).filter(Patient.worker_id == worker.worker_id).count()
        assert after == before
    finally:
        db.close()


def test_meera_is_left_unvisited_for_the_live_demo():
    """She is the patient the demo script records in front of an audience.
    Giving her seeded history would mean the risk shown on stage is not the
    one that was just spoken."""
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
        seed_demo_worker_caseload(db, patients_per_worker=8, months_history=3)

        worker = _demo_worker(db)
        # Filtered in Python, not SQL: Patient.name is encrypted at rest
        # (NFR-SC1) with a fresh nonce per write, so the same name encrypts
        # to different bytes every time and `Patient.name == "Meera Patil"`
        # can never match in a WHERE clause.
        meera = next(
            (
                p
                for p in db.query(Patient).filter(Patient.worker_id == worker.worker_id).all()
                if p.name == "Meera Patil"
            ),
            None,
        )
        assert meera is not None
        seeded = db.query(Visit).filter(
            Visit.patient_id == meera.patient_id,
            Visit.transcript == "[synthetic historical visit -- audio not retained]",
        ).count()
        assert seeded == 0
    finally:
        db.close()
