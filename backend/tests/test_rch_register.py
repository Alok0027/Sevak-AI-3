"""FR-05.2: the RCH register has to be a register -- one row per maternal
or under-5 patient, with her own fields -- not a bare count.

Before this, `rch_register_entries` was an integer incremented once per
matching *visit* (and it only counted pregnancy, silently excluding
every under-5 child), with nothing behind it a supervisor could actually
open and read.
"""
import json
import os
import uuid
from datetime import datetime, timezone

import pytest

from app.agents.agent4_reporting import build_rch_register, regenerate_monthly_report
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.db.session import SessionLocal
from app.services.pdf_generator import generate_hmis_pdf

TEST_MONTH = 6
TEST_YEAR = 2026


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _rch_number() -> str:
    return str(uuid.uuid4().int)[:12]


def _worker(db) -> str:
    w = Worker(name="Test ASHA", phone=str(uuid.uuid4())[:10], pin_hash="x", role="asha")
    db.add(w)
    db.flush()
    return w.worker_id


def _patient(db, worker_id: str, name: str, **fields) -> str:
    p = Patient(
        worker_id=worker_id, name=name,
        rch_number=fields.pop("rch_number", None), village=fields.pop("village", None),
    )
    db.add(p)
    db.flush()
    return p.patient_id


def _visit(db, worker_id, patient_id, *, risk_level="LOW", when=None, **extracted_fields) -> None:
    v = Visit(
        worker_id=worker_id,
        patient_id=patient_id,
        risk_level=risk_level,
        structured_json=json.dumps(extracted_fields),
        created_at=when or datetime(TEST_YEAR, TEST_MONTH, 15, tzinfo=timezone.utc),
    )
    db.add(v)
    db.flush()


def test_register_has_one_row_per_maternal_patient(db):
    worker_id = _worker(db)
    rch = _rch_number()
    meera = _patient(db, worker_id, "Meera Patil", rch_number=rch, village="Wagholi")
    _visit(db, worker_id, meera, risk_level="HIGH", pregnancy_stage="7 months", age=28)
    db.commit()

    register = build_rch_register(db, worker_id, TEST_MONTH, TEST_YEAR)
    assert len(register) == 1
    row = register[0]
    assert row["patient_name"] == "Meera Patil"
    assert row["rch_number"] == rch
    assert row["village"] == "Wagholi"
    assert row["category"] == "maternal"
    assert row["last_risk_level"] == "HIGH"
    assert row["anc_visits"] == 1


def test_register_includes_under_5_children_not_just_maternal_patients(db):
    """The prior count-only implementation only ever incremented on
    pregnancy_stage -- a registered child patient was invisible to it."""
    worker_id = _worker(db)
    baby = _patient(db, worker_id, "Infant Sharma")
    _visit(db, worker_id, baby, age=2)
    db.commit()

    register = build_rch_register(db, worker_id, TEST_MONTH, TEST_YEAR)
    assert len(register) == 1
    assert register[0]["category"] == "child"
    assert register[0]["patient_name"] == "Infant Sharma"


def test_register_excludes_non_rch_patients(db):
    """A general adult visit with no pregnancy and no under-5 age must
    not pad the register -- that was the whole point of scoping it."""
    worker_id = _worker(db)
    adult = _patient(db, worker_id, "Ramesh Kumar")
    _visit(db, worker_id, adult, age=45)
    db.commit()

    assert build_rch_register(db, worker_id, TEST_MONTH, TEST_YEAR) == []


def test_repeat_visits_collapse_to_one_row_with_a_visit_count(db):
    """Two ANC visits from the same pregnant patient this month is one
    register entry with anc_visits=2, not two entries -- a register is
    keyed by patient, a tally of visits is a different question."""
    worker_id = _worker(db)
    meera = _patient(db, worker_id, "Meera Patil")
    _visit(db, worker_id, meera, risk_level="MEDIUM",
           when=datetime(TEST_YEAR, TEST_MONTH, 3, tzinfo=timezone.utc), pregnancy_stage="5 months")
    _visit(db, worker_id, meera, risk_level="HIGH",
           when=datetime(TEST_YEAR, TEST_MONTH, 20, tzinfo=timezone.utc), pregnancy_stage="6 months")
    db.commit()

    register = build_rch_register(db, worker_id, TEST_MONTH, TEST_YEAR)
    assert len(register) == 1
    assert register[0]["anc_visits"] == 2
    # Most recent visit wins for "current status" fields.
    assert register[0]["last_risk_level"] == "HIGH"
    assert register[0]["pregnancy_stage"] == "6 months"


def test_monthly_report_entry_count_matches_the_registers_own_length(db):
    """rch_register_entries used to be tallied separately from the
    register with a slightly different rule (maternal visits only) --
    the two could silently disagree. They must now be the same number by
    construction."""
    worker_id = _worker(db)
    meera = _patient(db, worker_id, "Meera Patil")
    baby = _patient(db, worker_id, "Infant Sharma")
    _visit(db, worker_id, meera, pregnancy_stage="7 months", age=28)
    _visit(db, worker_id, baby, age=1)
    db.commit()

    report = regenerate_monthly_report(db, worker_id, TEST_MONTH, TEST_YEAR)
    data = json.loads(report.data_json)
    assert data["rch_register_entries"] == len(data["rch_register"]) == 2
    assert {r["category"] for r in data["rch_register"]} == {"maternal", "child"}


def test_hmis_pdf_renders_the_register_without_error(db):
    """The register is a list of dicts inside data_json -- the PDF used
    to str()-dump every top-level field into a two-column table, which
    for a list of dicts prints an unreadable Python repr instead of a
    table. This just has to not crash and has to produce a real file."""
    worker_id = _worker(db)
    meera = _patient(db, worker_id, "Meera Patil", rch_number=_rch_number())
    _visit(db, worker_id, meera, risk_level="HIGH", pregnancy_stage="7 months", age=28)
    db.commit()

    report = regenerate_monthly_report(db, worker_id, TEST_MONTH, TEST_YEAR)
    data = json.loads(report.data_json)
    path = generate_hmis_pdf(worker_id=worker_id, month=TEST_MONTH, year=TEST_YEAR, data=data)
    assert os.path.exists(path)
    assert os.path.getsize(path) > 0


def test_hmis_pdf_renders_with_an_empty_register(db):
    """A worker with no maternal/under-5 visits this month must still get
    a PDF -- the empty-register branch, not a crash on an empty list."""
    worker_id = _worker(db)
    adult = _patient(db, worker_id, "Ramesh Kumar")
    _visit(db, worker_id, adult, age=45)
    db.commit()

    report = regenerate_monthly_report(db, worker_id, TEST_MONTH, TEST_YEAR)
    data = json.loads(report.data_json)
    assert data["rch_register"] == []
    path = generate_hmis_pdf(worker_id=worker_id, month=TEST_MONTH, year=TEST_YEAR, data=data)
    assert os.path.exists(path)
