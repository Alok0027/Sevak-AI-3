"""POST /api/v1/visits/{visit_id}/resolve-risk: an ANM or BMO closes out an
open HIGH case with a mandatory clinical-review note. This is a distinct
action from risk-override (FR-03.3) -- it does NOT change the recorded risk
classification, it just marks the case reviewed and drops it off the
escalation queue, with a reason kept in the audit trail. Before this test
file, the endpoint (and its 10-character-minimum note requirement) had no
coverage at all.
"""
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


def _record_high_visit(client: TestClient, headers: dict, worker_id: str, patient_id: str) -> dict:
    audio_b64 = base64.b64encode(DEMO_TRANSCRIPT.encode()).decode()
    resp = client.post(
        "/api/v1/visits/voice",
        headers=headers,
        json={"worker_id": worker_id, "patient_id": patient_id, "audio_base64": audio_b64, "language_code": "hi"},
    )
    assert resp.status_code == 200, resp.text
    visit = resp.json()
    assert visit["risk_level"] == "HIGH"
    return visit


def _meera(client, headers, worker_id):
    patients = client.get(f"/api/v1/patients/{worker_id}", headers=headers)
    return next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")


def test_anm_can_resolve_a_high_case_with_a_note_and_it_drops_off_the_queue():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        asha_headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _meera(client, asha_headers, asha["worker_id"])
        visit = _record_high_visit(client, asha_headers, asha["worker_id"], meera["id"])

        anm = _login(client, "9999999901", "1234")  # Dr. Rekha Joshi, SC-PUNE-01
        anm_headers = {"Authorization": f"Bearer {anm['access_token']}"}

        pending_before = client.get("/api/v1/escalations/pending", headers=anm_headers)
        assert visit["visit_id"] in [e["visit_id"] for e in pending_before.json()["escalations"]]

        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/resolve-risk",
            headers=anm_headers,
            json={"note": "Called the patient directly, BP retest was normal today."},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "resolved"
        assert resp.json()["resolved_by"] == anm["worker_id"]

        pending_after = client.get("/api/v1/escalations/pending", headers=anm_headers)
        assert visit["visit_id"] not in [e["visit_id"] for e in pending_after.json()["escalations"]]

        # The risk classification itself is untouched -- resolution is a
        # separate human decision, not a relabelling.
        history = client.get(f"/api/v1/patients/{meera['id']}/history", headers=anm_headers)
        entry = next(v for v in history.json()["visits"] if v["visit_id"] == visit["visit_id"])
        assert entry["risk_level"] == "HIGH"
        assert entry["risk_resolved"] is True
        assert entry["risk_resolution_note"] == "Called the patient directly, BP retest was normal today."
        assert entry["resolved_by_name"] == "Dr. Rekha Joshi"
        assert entry["resolved_at"] is not None


def test_resolve_rejects_a_note_under_ten_characters():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        asha_headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _meera(client, asha_headers, asha["worker_id"])
        visit = _record_high_visit(client, asha_headers, asha["worker_id"], meera["id"])

        anm = _login(client, "9999999901", "1234")
        anm_headers = {"Authorization": f"Bearer {anm['access_token']}"}
        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/resolve-risk",
            headers=anm_headers,
            json={"note": "too short"},
        )
        assert resp.status_code == 422

        # Still open -- a rejected attempt must not silently resolve it.
        pending = client.get("/api/v1/escalations/pending", headers=anm_headers)
        assert visit["visit_id"] in [e["visit_id"] for e in pending.json()["escalations"]]


def test_an_asha_cannot_resolve_a_risk_flag():
    """Distinct from override, which an ASHA CAN do on her own visit --
    resolve-risk is an ANM/BMO-only clinical-review action (see
    resolve_risk()'s require_roles)."""
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        asha_headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _meera(client, asha_headers, asha["worker_id"])
        visit = _record_high_visit(client, asha_headers, asha["worker_id"], meera["id"])

        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/resolve-risk",
            headers=asha_headers,
            json={"note": "I checked on her myself and she's fine now."},
        )
        assert resp.status_code == 403


def test_anm_cannot_resolve_a_case_outside_her_sub_centre():
    with TestClient(app) as client:
        _seed()
        db = SessionLocal()
        try:
            from app.core.security import hash_pin
            from app.db.models.worker import Worker

            if not db.query(Worker).filter(Worker.phone == "9111111111").first():
                db.add(Worker(name="Other Test ASHA", phone="9111111111", pin_hash=hash_pin("1234"),
                               language_pref="hi", sub_centre_id="SC-TEST-OUTSIDE", role="asha"))
                db.commit()
        finally:
            db.close()

        other = _login(client, "9111111111", "1234")
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        other_patient = client.post(
            "/api/v1/patients", headers=other_headers,
            json={"name": "Outside Sub-Centre Patient", "age": 30, "gender": "female"},
        )
        assert other_patient.status_code == 201, other_patient.text
        visit = _record_high_visit(client, other_headers, other["worker_id"], other_patient.json()["id"])

        anm = _login(client, "9999999901", "1234")  # SC-PUNE-01 -- not this worker's sub-centre
        anm_headers = {"Authorization": f"Bearer {anm['access_token']}"}
        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/resolve-risk",
            headers=anm_headers,
            json={"note": "Outside my sub-centre -- shouldn't be allowed."},
        )
        assert resp.status_code == 403


def test_resolving_twice_is_idempotent_not_an_error():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        asha_headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _meera(client, asha_headers, asha["worker_id"])
        visit = _record_high_visit(client, asha_headers, asha["worker_id"], meera["id"])

        anm = _login(client, "9999999901", "1234")
        anm_headers = {"Authorization": f"Bearer {anm['access_token']}"}
        first = client.post(
            f"/api/v1/visits/{visit['visit_id']}/resolve-risk",
            headers=anm_headers, json={"note": "First clinical review note, all normal."},
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/v1/visits/{visit['visit_id']}/resolve-risk",
            headers=anm_headers, json={"note": "A different note on a second attempt."},
        )
        assert second.status_code == 200
        assert second.json()["resolved_by"] == first.json()["resolved_by"]

        # The original note wins -- a second call must not overwrite it.
        history = client.get(f"/api/v1/patients/{meera['id']}/history", headers=anm_headers)
        entry = next(v for v in history.json()["visits"] if v["visit_id"] == visit["visit_id"])
        assert entry["risk_resolution_note"] == "First clinical review note, all normal."
