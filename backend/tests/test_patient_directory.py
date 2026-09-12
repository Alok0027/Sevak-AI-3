"""FR-08 drill-down: GET /api/v1/patients (no worker_id) -- the cross-worker
patient directory an ANM/BMO needs, since GET /api/v1/patients/{worker_id}
only ever shows one ASHA's patients at a time."""
import base64

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures

DEMO_TRANSCRIPT = (
    "Meera Patil, 28 saal, 7 mahine ki pregnancy. Aaj BP 140 over 90 tha. "
    "Usne pichle 2 hafte se iron tablets nahi li. Pati bahar gaya hua hai."
)


def _login(client: TestClient, phone: str, pin: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed():
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
    finally:
        db.close()


def _seed_patient_outside_pune01():
    """One ASHA and one patient in a second sub-centre, so "district-wide
    really is wider than one sub-centre" has something to be true about.
    Idempotent, so repeated calls within a run don't multiply rows."""
    from app.core.security import hash_pin
    from app.db.models.patient import Patient
    from app.db.models.worker import Worker

    db = SessionLocal()
    try:
        worker = db.query(Worker).filter(Worker.phone == "9999990077").first()
        if worker is None:
            worker = Worker(
                name="Tanvi Kohli",
                phone="9999990077",
                pin_hash=hash_pin("1234"),
                language_pref="mr",
                sub_centre_id="SC-TEST-OUTSIDE",
                role="asha",
            )
            db.add(worker)
            db.commit()
            db.refresh(worker)

        exists = db.query(Patient).filter(Patient.worker_id == worker.worker_id).first()
        if exists is None:
            db.add(Patient(worker_id=worker.worker_id, name="Outside Sub-Centre Patient", age=30))
            db.commit()
    finally:
        db.close()


def test_asha_cannot_use_the_district_wide_directory():
    """She has her own GET /patients/{worker_id} -- this endpoint is for
    her supervisors, not her."""
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        resp = client.get("/api/v1/patients", headers=headers)
        assert resp.status_code == 403


def test_anm_sees_her_sub_centres_patients_including_meera():
    with TestClient(app) as client:
        _seed()
        anm = _login(client, "9999999901", "1234")  # Dr. Rekha Joshi, SC-PUNE-01
        headers = {"Authorization": f"Bearer {anm['access_token']}"}
        resp = client.get("/api/v1/patients", headers=headers)
        assert resp.status_code == 200, resp.text
        patients = resp.json()["patients"]
        assert any(p["name"] == "Meera Patil" for p in patients)
        # Every entry must actually belong to her own sub-centre.
        assert all(p["sub_centre_id"] == "SC-PUNE-01" for p in patients)
        # And it carries the fields a directory needs that the per-worker
        # list doesn't: gender, registration date, which worker treats them.
        meera = next(p for p in patients if p["name"] == "Meera Patil")
        assert meera["gender"] == "female"
        assert meera["registered_at"] is not None
        assert meera["worker_name"] == "Sunita Sharma"


def test_bmo_sees_district_wide_and_can_filter_to_one_sub_centre():
    with TestClient(app) as client:
        _seed()
        # Create the second sub-centre this test needs rather than hoping
        # one is lying around. It used to rely on the database already
        # containing patients from other sub-centres, which was true only
        # because the suite shared the dev database and earlier runs had
        # left some behind -- so the test passed for a reason that had
        # nothing to do with the code under test.
        _seed_patient_outside_pune01()

        bmo = _login(client, "9999999902", "1234")
        headers = {"Authorization": f"Bearer {bmo['access_token']}"}

        district_wide = client.get("/api/v1/patients", headers=headers)
        assert district_wide.status_code == 200
        all_patients = district_wide.json()["patients"]
        assert any(p["name"] == "Meera Patil" for p in all_patients)
        assert any(p["sub_centre_id"] != "SC-PUNE-01" for p in all_patients)

        scoped = client.get("/api/v1/patients", headers=headers, params={"sub_centre_id": "SC-PUNE-01"})
        assert scoped.status_code == 200
        scoped_patients = scoped.json()["patients"]
        assert all(p["sub_centre_id"] == "SC-PUNE-01" for p in scoped_patients)
        assert len(scoped_patients) < len(all_patients)


def test_directory_reflects_a_real_visit_risk_level():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        asha_headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=asha_headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")

        audio_b64 = base64.b64encode(DEMO_TRANSCRIPT.encode()).decode()
        visit = client.post(
            "/api/v1/visits/voice",
            headers=asha_headers,
            json={
                "worker_id": asha["worker_id"],
                "patient_id": meera["id"],
                "audio_base64": audio_b64,
                "language_code": "hi",
            },
        )
        assert visit.status_code == 200, visit.text

        anm = _login(client, "9999999901", "1234")
        anm_headers = {"Authorization": f"Bearer {anm['access_token']}"}
        directory = client.get("/api/v1/patients", headers=anm_headers)
        meera_entry = next(p for p in directory.json()["patients"] if p["name"] == "Meera Patil")
        assert meera_entry["risk_status"] == "HIGH"
        assert meera_entry["total_visits"] >= 1
