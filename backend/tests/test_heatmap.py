"""FR-08.1: the district heatmap has to describe villages truthfully.

Three things were wrong with it before, and none of them were visible
from the map itself, which is why they lasted:

1. It emitted one point per (village, risk_level) pair -- several dots
   stacked on the identical coordinate, the worst drawn over the rest.
2. `patient_count` counted *visits*. A village whose one patient was seen
   twelve times reported "12 patients".
3. Every coordinate was a hash of the village's name, so the dots were in
   the wrong places entirely.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.db.session import SessionLocal
from app.services import geo

BASE = datetime(2026, 5, 1, tzinfo=timezone.utc)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _worker(db) -> Worker:
    w = Worker(name="Heatmap ASHA", phone=str(uuid.uuid4())[:10], pin_hash="x", role="asha",
               sub_centre_id=f"SC-HEAT-{uuid.uuid4().hex[:6]}")
    db.add(w)
    db.flush()
    return w


def _patient(db, worker, village) -> Patient:
    p = Patient(worker_id=worker.worker_id, name="Test Patient", village=village)
    db.add(p)
    db.flush()
    return p


def _visit(db, worker, patient, risk_level, *, days=0) -> None:
    db.add(Visit(worker_id=worker.worker_id, patient_id=patient.patient_id,
                 risk_level=risk_level, created_at=BASE + timedelta(days=days)))
    db.flush()


def _heatmap_for(db, worker):
    """Call the endpoint's own logic against this worker's sub-centre, so
    the test reads what the dashboard would render, not a helper."""
    from app.api.routes.dashboard import heatmap

    class _User:
        role = "anm"
        worker_id = worker.worker_id
        sub_centre_id = worker.sub_centre_id

    # get_supervisor_scope reads the ANM's own sub_centre_id off the user.
    return {p.village: p for p in heatmap(db=db, user=_User()).risk_points}


# ── geo.locate ───────────────────────────────────────────────────────────

def test_a_known_village_gets_its_real_position_not_a_hash():
    """Wagholi is ~15km east of Pune. The old hash put it wherever
    sha256 felt like, which for a district map is simply wrong."""
    lat, lng, approximate = geo.locate("Wagholi")
    assert approximate is False
    assert 18.5 < lat < 18.7
    assert 73.9 < lng < 74.1


def test_village_lookup_ignores_case_and_spacing():
    """Same key the rest of the app groups villages by (identity.village_code)
    -- "wagholi" typed at 6am is not a different place."""
    assert geo.locate("  wagholi ") == geo.locate("Wagholi")


def test_an_unknown_village_is_placed_but_flagged_approximate():
    lat, lng, approximate = geo.locate("Some Unlisted Hamlet")
    assert approximate is True
    assert 17.5 <= lat <= 21.5 and 73.0 <= lng <= 76.5
    # Stable between calls -- a dot that moves on every refresh reads as a
    # bug even when the underlying data is fine.
    assert geo.locate("Some Unlisted Hamlet") == (lat, lng, approximate)


def test_a_missing_village_name_still_resolves():
    lat, lng, approximate = geo.locate(None)
    assert approximate is True
    assert isinstance(lat, float) and isinstance(lng, float)


# ── aggregation ──────────────────────────────────────────────────────────

def test_one_point_per_village_not_one_per_risk_level(db):
    worker = _worker(db)
    _visit(db, worker, _patient(db, worker, "Wagholi"), "HIGH")
    _visit(db, worker, _patient(db, worker, "Wagholi"), "LOW")
    _visit(db, worker, _patient(db, worker, "Wagholi"), "LOW")
    db.commit()

    points = _heatmap_for(db, worker)
    assert list(points) == ["Wagholi"]
    point = points["Wagholi"]
    assert point.patient_count == 3
    assert (point.high_count, point.medium_count, point.low_count) == (1, 0, 2)
    # The counts are the whole story of the village, not a sample of it.
    assert point.high_count + point.medium_count + point.low_count == point.patient_count


def test_patient_count_counts_patients_not_visits(db):
    """One woman seen four times is one patient. The old implementation
    reported this village as having four."""
    worker = _worker(db)
    patient = _patient(db, worker, "Shirur")
    for day in range(4):
        _visit(db, worker, patient, "MEDIUM", days=day)
    db.commit()

    point = _heatmap_for(db, worker)["Shirur"]
    assert point.patient_count == 1
    assert point.visit_count == 4


def test_the_split_follows_each_patients_latest_visit(db):
    """A patient flagged HIGH and later cleared is a LOW patient now. The
    map is a picture of today, not an archive of everything ever read."""
    worker = _worker(db)
    patient = _patient(db, worker, "Baramati")
    _visit(db, worker, patient, "HIGH", days=0)
    _visit(db, worker, patient, "LOW", days=5)
    db.commit()

    point = _heatmap_for(db, worker)["Baramati"]
    assert (point.high_count, point.low_count) == (0, 1)
    assert point.risk_level == "LOW"
    assert point.visit_count == 2


def test_worst_open_risk_colours_the_village(db):
    worker = _worker(db)
    _visit(db, worker, _patient(db, worker, "Daund"), "LOW")
    _visit(db, worker, _patient(db, worker, "Daund"), "MEDIUM")
    db.commit()
    assert _heatmap_for(db, worker)["Daund"].risk_level == "MEDIUM"

    _visit(db, worker, _patient(db, worker, "Daund"), "HIGH")
    db.commit()
    assert _heatmap_for(db, worker)["Daund"].risk_level == "HIGH"


def test_last_visit_is_the_most_recent_one_in_the_village(db):
    worker = _worker(db)
    _visit(db, worker, _patient(db, worker, "Junnar"), "LOW", days=0)
    _visit(db, worker, _patient(db, worker, "Junnar"), "LOW", days=9)
    db.commit()

    point = _heatmap_for(db, worker)["Junnar"]
    assert point.last_visit_at.replace(tzinfo=timezone.utc) == BASE + timedelta(days=9)


def test_points_come_back_worst_first(db):
    """The dashboard draws them in order, so a HIGH village's dot lands
    on top of a quiet neighbour's rather than under it."""
    worker = _worker(db)
    _visit(db, worker, _patient(db, worker, "Velhe"), "LOW")
    _visit(db, worker, _patient(db, worker, "Khed"), "HIGH")
    _visit(db, worker, _patient(db, worker, "Mulshi"), "MEDIUM")
    db.commit()

    from app.api.routes.dashboard import heatmap

    class _User:
        role = "anm"
        worker_id = worker.worker_id
        sub_centre_id = worker.sub_centre_id

    levels = [p.risk_level for p in heatmap(db=db, user=_User()).risk_points]
    assert levels == ["HIGH", "MEDIUM", "LOW"]


def test_a_villages_dot_sits_where_the_village_is(db):
    """End to end: the endpoint resolves through the gazetteer, so two
    real neighbours come back as neighbours."""
    worker = _worker(db)
    _visit(db, worker, _patient(db, worker, "Wagholi"), "HIGH")
    _visit(db, worker, _patient(db, worker, "Pune Rural"), "LOW")
    db.commit()

    points = _heatmap_for(db, worker)
    assert points["Wagholi"].approximate_location is False
    # Wagholi is east of Pune, and within ~20km of it.
    assert points["Wagholi"].lng > points["Pune Rural"].lng
    assert abs(points["Wagholi"].lat - points["Pune Rural"].lat) < 0.2


def test_an_unmapped_village_is_marked_approximate_end_to_end(db):
    worker = _worker(db)
    _visit(db, worker, _patient(db, worker, "Nowhere Wadi"), "LOW")
    db.commit()
    assert _heatmap_for(db, worker)["Nowhere Wadi"].approximate_location is True
