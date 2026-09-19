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


def _seed_asha_with_patient(*, phone: str, name: str, sub_centre_id: str, patient_name: str):
    """One ASHA and one patient in a given sub-centre. Idempotent, so
    repeated calls within a run don't multiply rows."""
    from app.core.security import hash_pin
    from app.db.models.patient import Patient
    from app.db.models.worker import Worker
    from app.services import identity

    db = SessionLocal()
    try:
        worker = db.query(Worker).filter(Worker.phone == phone).first()
        if worker is None:
            worker = Worker(
                name=name,
                phone=phone,
                pin_hash=hash_pin("1234"),
                language_pref="mr",
                sub_centre_id=sub_centre_id,
                district_id=identity.district_code(sub_centre_id),
                role="asha",
            )
            db.add(worker)
            db.commit()
            db.refresh(worker)

        exists = db.query(Patient).filter(Patient.worker_id == worker.worker_id).first()
        if exists is None:
            db.add(Patient(worker_id=worker.worker_id, name=patient_name, age=30))
            db.commit()
    finally:
        db.close()


def _seed_second_pune_sub_centre():
    """A second sub-centre inside the BMO's own district (PUNE), so
    "a BMO sees more than one sub-centre" has something to be true of."""
    _seed_asha_with_patient(
        phone="9999990078", name="Asha Pawar", sub_centre_id="SC-PUNE-02",
        patient_name="Second Sub-Centre Patient",
    )


def _seed_patient_in_another_district():
    """An ASHA in a different district entirely. A Pune BMO must not be
    able to read her patients."""
    _seed_asha_with_patient(
        phone="9999990077", name="Tanvi Kohli", sub_centre_id="SC-NASHIK-01",
        patient_name="Other District Patient",
    )


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


def test_bmo_sees_every_sub_centre_in_her_district_and_none_outside_it():
    """SRS table 4: a BMO oversees multiple sub-centres -- within one
    district. This used to assert only the first half, and passed because
    the endpoint applied no filter at all for a BMO: "district-wide" was
    implemented as "every row in the database", which in a real
    deployment is every district in the state."""
    with TestClient(app) as client:
        _seed()
        _seed_second_pune_sub_centre()
        _seed_patient_in_another_district()

        bmo = _login(client, "9999999902", "1234")  # Dr. Vikram Rao, PUNE
        headers = {"Authorization": f"Bearer {bmo['access_token']}"}

        district_wide = client.get("/api/v1/patients", headers=headers)
        assert district_wide.status_code == 200
        all_patients = district_wide.json()["patients"]

        # Wider than one sub-centre...
        assert any(p["name"] == "Meera Patil" for p in all_patients)
        assert any(p["sub_centre_id"] == "SC-PUNE-02" for p in all_patients)
        # ...and no wider than one district.
        assert all(p["sub_centre_id"].startswith("SC-PUNE-") for p in all_patients)
        assert not any(p["name"] == "Other District Patient" for p in all_patients)

        scoped = client.get("/api/v1/patients", headers=headers, params={"sub_centre_id": "SC-PUNE-01"})
        assert scoped.status_code == 200
        scoped_patients = scoped.json()["patients"]
        assert all(p["sub_centre_id"] == "SC-PUNE-01" for p in scoped_patients)
        assert len(scoped_patients) < len(all_patients)


def test_a_bmo_cannot_reach_another_districts_sub_centre_by_asking_for_it():
    """The sub_centre_id parameter narrows what a caller may see; it must
    not be a way around the scope."""
    with TestClient(app) as client:
        _seed()
        _seed_patient_in_another_district()

        bmo = _login(client, "9999999902", "1234")
        headers = {"Authorization": f"Bearer {bmo['access_token']}"}
        resp = client.get("/api/v1/patients", headers=headers, params={"sub_centre_id": "SC-NASHIK-01"})
        assert resp.status_code == 403


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
