"""SRS table 4, the half that was never enforced: a BMO oversees the
sub-centres in *one district*.

get_supervisor_scope() returned None for a BMO -- meaning no filter at
all -- and every district-wide endpoint took that to mean "every row in
the database". In the demo database, which only ever contained Pune,
that is indistinguishable from correct district scoping. In a real
deployment it means any BMO in the state can read any other district's
patients, workers, escalations and heatmap.

This file exists to make that difference visible: it puts two districts
in the database and checks every supervisor-facing endpoint from a Pune
BMO's session. An endpoint added later that forgets to scope will fail
here rather than in a state rollout.
"""
import base64

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_pin
from app.db.models.patient import Patient
from app.db.models.visit import Visit
from app.db.models.worker import Worker
from app.db.session import SessionLocal
from app.main import app
from app.services import identity
from scripts.seed_synthetic_data import seed_demo_fixtures

NASHIK_ASHA_PHONE = "9333300001"
NASHIK_BMO_PHONE = "9333300002"
PUNE_2_ASHA_PHONE = "9333300003"


def _login(client: TestClient, phone: str, pin: str = "1234") -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _worker(db, *, phone, name, role, sub_centre_id=None, district_id=None) -> Worker:
    existing = db.query(Worker).filter(Worker.phone == phone).first()
    if existing:
        return existing
    worker = Worker(
        name=name, phone=phone, pin_hash=hash_pin("1234"), role=role,
        sub_centre_id=sub_centre_id,
        district_id=district_id or identity.district_code(sub_centre_id),
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def _patient_of(db, worker) -> Patient | None:
    """Patient.name is encrypted at rest, so it cannot be used in a WHERE
    clause -- every lookup here goes through the worker instead."""
    return db.query(Patient).filter(Patient.worker_id == worker.worker_id).first()


def _patient_with_visit(db, worker, *, name, village, risk_level="HIGH") -> Patient:
    patient = _patient_of(db, worker)
    if patient is None:
        patient = Patient(worker_id=worker.worker_id, name=name, village=village, age=27)
        db.add(patient)
        db.commit()
        db.refresh(patient)
        db.add(Visit(worker_id=worker.worker_id, patient_id=patient.patient_id, risk_level=risk_level))
        db.commit()
    return patient


@pytest.fixture
def two_districts():
    """Pune (the demo district, two sub-centres) and Nashik (one), each
    with a patient carrying a HIGH visit so every risk-driven endpoint
    has something to leak if it is going to."""
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
        pune2 = _worker(db, phone=PUNE_2_ASHA_PHONE, name="Asha Pawar",
                        role="asha", sub_centre_id="SC-PUNE-02")
        nashik = _worker(db, phone=NASHIK_ASHA_PHONE, name="Kavita More",
                         role="asha", sub_centre_id="SC-NASHIK-01")
        _worker(db, phone=NASHIK_BMO_PHONE, name="Dr. Nashik BMO",
                role="bmo", district_id="NASHIK")
        _patient_with_visit(db, pune2, name="Pune Two Patient", village="Wadeshwar Colony")
        _patient_with_visit(db, nashik, name="Nashik Patient", village="Sinnar")
        yield
    finally:
        db.close()


@pytest.fixture
def pune_bmo(two_districts):
    with TestClient(app) as client:
        session = _login(client, "9999999902")  # Dr. Vikram Rao, PUNE
        yield client, {"Authorization": f"Bearer {session['access_token']}"}


# ── the heatmap the user is actually looking at ──────────────────────────

def test_the_heatmap_shows_the_bmos_own_district_only(pune_bmo):
    client, headers = pune_bmo
    resp = client.get("/api/v1/dashboard/heatmap", headers=headers)
    assert resp.status_code == 200
    villages = {p["village"] for p in resp.json()["risk_points"]}
    assert "Wadeshwar Colony" in villages           # SC-PUNE-02, same district
    assert "Sinnar" not in villages       # Nashik's village


def test_an_anm_sees_only_her_own_sub_centre_on_the_heatmap(two_districts):
    """Tighter than the BMO: an ANM gets her sub-centre, not her
    district (SRS: "cannot access district-level data")."""
    with TestClient(app) as client:
        anm = _login(client, "9999999901")  # SC-PUNE-01
        headers = {"Authorization": f"Bearer {anm['access_token']}"}
        villages = {
            p["village"] for p in client.get("/api/v1/dashboard/heatmap", headers=headers).json()["risk_points"]
        }
        assert "Wadeshwar Colony" not in villages   # SC-PUNE-02 -- her district, not her sub-centre
        # Not drawn from seed_synthetic_data.VILLAGES, so a randomly-seeded
        # demo patient can never coincidentally land here (see test_heatmap.py
        # for the analogous village-name collision this sidesteps).
        assert "Sinnar" not in villages


def test_an_unmapped_village_is_placed_inside_the_district_not_across_the_state(pune_bmo):
    """A village the gazetteer doesn't know used to be scattered anywhere
    in Maharashtra, which dragged the map's auto-framing out to the whole
    state. It now lands near its own district's centre."""
    db = SessionLocal()
    try:
        worker = db.query(Worker).filter(Worker.phone == PUNE_2_ASHA_PHONE).first()
        patient = Patient(worker_id=worker.worker_id, name="Unmapped Village Patient",
                          village="Totally Unlisted Wadi", age=31)
        db.add(patient)
        db.commit()
        db.add(Visit(worker_id=worker.worker_id, patient_id=patient.patient_id, risk_level="LOW"))
        db.commit()
    finally:
        db.close()

    client, headers = pune_bmo
    points = {p["village"]: p for p in client.get("/api/v1/dashboard/heatmap", headers=headers).json()["risk_points"]}
    point = points["Totally Unlisted Wadi"]
    assert point["approximate_location"] is True
    assert abs(point["lat"] - 18.62) < 0.3
    assert abs(point["lng"] - 74.10) < 0.3


# ── every other supervisor endpoint ──────────────────────────────────────

def test_the_patient_directory_stops_at_the_district_line(pune_bmo):
    client, headers = pune_bmo
    names = {p["name"] for p in client.get("/api/v1/patients", headers=headers).json()["patients"]}
    assert "Pune Two Patient" in names
    assert "Nashik Patient" not in names


def test_the_worker_roster_stops_at_the_district_line(pune_bmo):
    client, headers = pune_bmo
    names = {w["name"] for w in client.get("/api/v1/workers", headers=headers).json()["workers"]}
    assert "Asha Pawar" in names
    assert "Kavita More" not in names


def test_the_escalation_queue_stops_at_the_district_line(pune_bmo):
    client, headers = pune_bmo
    resp = client.get("/api/v1/escalations/pending", headers=headers)
    assert resp.status_code == 200
    patients = {e["patient"] for e in resp.json()["escalations"]}
    assert "Nashik Patient" not in patients


def test_headline_metrics_do_not_count_another_districts_cases(pune_bmo):
    """The stat tiles are a count, so a leak here is invisible rather
    than obviously wrong -- which makes it worth pinning down."""
    client, headers = pune_bmo
    pune_high = client.get("/api/v1/dashboard/metrics", headers=headers).json()["high_risk_cases"]

    with TestClient(app) as other:
        nashik = _login(other, NASHIK_BMO_PHONE)
        nashik_headers = {"Authorization": f"Bearer {nashik['access_token']}"}
        nashik_high = other.get("/api/v1/dashboard/metrics", headers=nashik_headers).json()["high_risk_cases"]

    assert nashik_high == 1  # her own district's single HIGH case, and no more
    assert pune_high >= 1


def test_a_bmo_cannot_open_another_districts_worker(pune_bmo):
    client, headers = pune_bmo
    db = SessionLocal()
    try:
        outsider = db.query(Worker).filter(Worker.phone == NASHIK_ASHA_PHONE).first().worker_id
    finally:
        db.close()
    assert client.get(f"/api/v1/workers/{outsider}/history", headers=headers).status_code == 403


def test_a_bmo_cannot_open_another_districts_patient(pune_bmo):
    client, headers = pune_bmo
    db = SessionLocal()
    try:
        nashik_asha = db.query(Worker).filter(Worker.phone == NASHIK_ASHA_PHONE).first()
        outsider = _patient_of(db, nashik_asha).patient_id
    finally:
        db.close()
    assert client.get(f"/api/v1/patients/{outsider}/history", headers=headers).status_code == 403


def test_a_bmo_cannot_resolve_a_risk_in_another_district(pune_bmo):
    """Not just reads: the write paths take the same scope."""
    client, headers = pune_bmo
    db = SessionLocal()
    try:
        nashik_asha = db.query(Worker).filter(Worker.phone == NASHIK_ASHA_PHONE).first()
        patient = _patient_of(db, nashik_asha)
        visit = db.query(Visit).filter(Visit.patient_id == patient.patient_id).first().visit_id
    finally:
        db.close()
    resp = client.post(f"/api/v1/visits/{visit}/resolve-risk", headers=headers,
                       json={"note": "Reaching across a district boundary."})
    assert resp.status_code == 403


def test_a_bmo_cannot_override_a_risk_in_another_district(pune_bmo):
    """override_risk had its own, older scope check that predates
    visible_sub_centres and never got the district split -- it let a BMO
    through with an explicit 'district-wide, no restriction' comment, the
    exact bug this file exists to catch, just on a different endpoint."""
    client, headers = pune_bmo
    db = SessionLocal()
    try:
        nashik_asha = db.query(Worker).filter(Worker.phone == NASHIK_ASHA_PHONE).first()
        patient = _patient_of(db, nashik_asha)
        visit = db.query(Visit).filter(Visit.patient_id == patient.patient_id).first().visit_id
    finally:
        db.close()
    resp = client.post(f"/api/v1/visits/{visit}/risk-override", headers=headers,
                       json={"new_risk_level": "LOW", "reason": "Reaching across a district boundary."})
    assert resp.status_code == 403


# ── fail closed ──────────────────────────────────────────────────────────

def test_a_bmo_with_no_district_is_refused_rather_than_given_everything(two_districts):
    """The whole point of the column: missing scope must fail closed. An
    unassigned BMO used to be the one caller who saw the entire country."""
    db = SessionLocal()
    try:
        stray = _worker(db, phone="9333300009", name="Dr. Unassigned", role="bmo")
        stray.district_id = None
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        session = _login(client, "9333300009")
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        for path in ("/api/v1/patients", "/api/v1/workers", "/api/v1/dashboard/heatmap"):
            assert client.get(path, headers=headers).status_code == 403, path


def test_district_is_filled_in_for_workers_that_predate_the_column(two_districts):
    """The backfill reads it out of the sub-centre id, so an existing
    database upgrades itself instead of locking its supervisors out."""
    from app.db.session import backfill_identity

    db = SessionLocal()
    try:
        worker = db.query(Worker).filter(Worker.phone == PUNE_2_ASHA_PHONE).first()
        worker.district_id = None
        db.commit()
    finally:
        db.close()

    backfill_identity()

    db = SessionLocal()
    try:
        worker = db.query(Worker).filter(Worker.phone == PUNE_2_ASHA_PHONE).first()
        assert worker.district_id == "PUNE"
    finally:
        db.close()


def test_an_admin_cannot_read_patient_records_but_keeps_the_system_it_administers():
    """SRS table 4: the Admin role has worker onboarding, protocol
    configuration and user management, and *no patient record access*.

    It had that access for a long time because the role list was written
    once and copied onto each new endpoint as it appeared. A system
    administrator who can read every pregnant woman's clinical history in
    the state is a standing DPDP exposure with no operational reason
    behind it -- nothing an admin actually does needs a patient's name.
    """
    from fastapi.testclient import TestClient

    from app.db.session import SessionLocal
    from app.main import app
    from scripts.seed_synthetic_data import seed_demo_fixtures

    with TestClient(app) as client:
        db = SessionLocal()
        try:
            seed_demo_fixtures(db)
        finally:
            db.close()

        admin = client.post(
            "/api/v1/auth/login", json={"phone": "9999999903", "pin": "1234"}
        ).json()
        headers = {"Authorization": f"Bearer {admin['access_token']}"}

        asha = client.post(
            "/api/v1/auth/login", json={"phone": "9999999999", "pin": "1234"}
        ).json()

        # Closed: anything that resolves to an identifiable patient.
        closed = [
            "/api/v1/patients",
            f"/api/v1/patients/{asha['worker_id']}",
            "/api/v1/reports/hmis/%s/6/2026" % asha["worker_id"],
        ]
        for path in closed:
            resp = client.get(path, headers=headers)
            assert resp.status_code == 403, (
                f"{path} served patient data to an admin ({resp.status_code})"
            )

        # Open: the system an admin is actually responsible for. These are
        # aggregates -- counts and village totals -- with no identities in
        # them, so closing them would cost oversight and protect nobody.
        for path in [
            "/api/v1/dashboard/metrics",
            "/api/v1/dashboard/heatmap",
            "/api/v1/workers",
            "/api/v1/admin/staff",
            "/api/v1/admin/audit-log",
        ]:
            resp = client.get(path, headers=headers)
            assert resp.status_code == 200, (
                f"{path} should stay open to an admin, got {resp.status_code}"
            )


def test_no_endpoint_an_admin_can_reach_returns_a_patient_name():
    """The test I should have written the first time.

    Closing /patients and /reports to the admin role was not enough: the
    escalation queue and the follow-up compliance view also name patients
    -- her name, age, village and the clinical reason she was flagged --
    and both were still open. The block could be walked around from the
    Overview screen without trying.

    So this does not check a list of endpoints someone remembered. It
    walks every GET path in the OpenAPI schema, calls each one with an
    admin token, and fails if a real patient's name appears in any
    response that succeeds.

    (Routes are read from app.openapi(), not app.routes: included routers
    nest, so app.routes lists 17 entries and none of the real ones -- a
    first version of this test scanned zero endpoints and passed.)
    """
    from fastapi.testclient import TestClient

    from app.db.models.patient import Patient
    from app.db.session import SessionLocal
    from app.main import app
    from scripts.seed_synthetic_data import seed_demo_fixtures

    with TestClient(app) as client:
        db = SessionLocal()
        try:
            seed_demo_fixtures(db)
            names = {p.name for p in db.query(Patient).all() if p.name}
            any_patient = db.query(Patient).first()
            patient_id = any_patient.patient_id if any_patient else "none"
        finally:
            db.close()
        assert names, "no patients seeded, so this test proves nothing"

        admin = client.post(
            "/api/v1/auth/login", json={"phone": "9999999903", "pin": "1234"}
        ).json()
        asha = client.post(
            "/api/v1/auth/login", json={"phone": "9999999999", "pin": "1234"}
        ).json()
        headers = {"Authorization": f"Bearer {admin['access_token']}"}

        # Put a real HIGH-risk case on the board first.
        #
        # Without this the escalation queue and the compliance view come
        # back empty, every response is name-free, and the scan passes
        # while proving nothing -- which is exactly what happened when
        # this test was first written. A leak test needs something to
        # leak.
        import base64

        asha_headers = {"Authorization": f"Bearer {asha['access_token']}"}
        transcript = (
            "Meera Patil, 28 saal, 7 mahine ki pregnancy. Aaj BP 160 over 110 tha. "
            "Usne pichle 2 hafte se iron tablets nahi li."
        )
        visit = client.post(
            "/api/v1/visits/voice",
            headers=asha_headers,
            json={
                "worker_id": asha["worker_id"],
                "patient_id": patient_id,
                "audio_base64": base64.b64encode(transcript.encode()).decode(),
                "language_code": "hi",
            },
        )
        assert visit.status_code == 200, visit.text
        assert visit.json()["risk_level"] == "HIGH", "expected a HIGH case to exist"

        # And confirm a supervisor who *may* see names actually does, so
        # the scan below is looking at populated responses.
        anm = client.post(
            "/api/v1/auth/login", json={"phone": "9999999901", "pin": "1234"}
        ).json()
        probe = client.get(
            "/api/v1/escalations/pending",
            headers={"Authorization": f"Bearer {anm['access_token']}"},
        )
        assert probe.status_code == 200 and any(
            name in probe.text for name in names
        ), "the escalation queue is empty, so this scan would prove nothing"

        substitutions = {
            "{worker_id}": asha["worker_id"],
            "{patient_id}": patient_id,
            "{month}": "6",
            "{year}": "2026",
        }

        checked, leaked = [], []
        for raw_path, methods in app.openapi()["paths"].items():
            if "get" not in methods or not raw_path.startswith("/api/"):
                continue
            path = raw_path
            for token, value in substitutions.items():
                path = path.replace(token, value)
            if "{" in path:
                continue  # a path parameter with no sensible value here
            resp = client.get(path, headers=headers)
            checked.append(raw_path)
            if resp.status_code != 200:
                continue  # refused, which is the point
            body = resp.text
            if any(name in body for name in names):
                leaked.append(raw_path)

        # Guard against the failure mode this test already had once: a
        # scan that silently covers nothing and reports success.
        assert len(checked) >= 10, f"only scanned {len(checked)} endpoints: {checked}"
        assert not leaked, f"an admin can read patient names from: {leaked}"
