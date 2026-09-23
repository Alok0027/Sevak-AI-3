"""Corrections and closures -- the two things every paper register has and
this one did not.

Before these endpoints the whole API had exactly one PUT/PATCH/DELETE, and
it cancelled a leave request. A name Bhashini misheard at registration
followed the woman through every referral letter for the life of the
record; a blood pressure misheard as 140/90 kept driving her risk score and
her follow-up deadline forever; and a patient who moved away or died stayed
on the caseload generating overdue tasks that could never be completed.
"""
import base64
import uuid

from fastapi.testclient import TestClient

from app.db.models.action import Action
from app.db.models.audit_log import AuditLog
from app.db.models.patient import Patient
from app.db.models.risk_flag import RiskFlag
from app.db.models.visit import Visit
from app.db.session import SessionLocal
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures

DEMO_TRANSCRIPT = (
    "Meera Patil, 28 saal, 7 mahine ki pregnancy. Aaj BP 140 over 90 tha. "
    "Usne pichle 2 hafte se iron tablets nahi li. Pati bahar gaya hua hai."
)


def _seed():
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
    finally:
        db.close()


def _login(client, phone="9999999999", pin="1234"):
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _patient(client, headers, name=None):
    """A fresh patient per test.

    These tests share one database and several of them rename or close the
    patient they act on, so reusing the seeded demo fixture made every test
    after the first depend on which ones had already run.
    """
    resp = client.post(
        "/api/v1/patients",
        headers=headers,
        json={
            "name": name or f"Test Patient {uuid.uuid4().hex[:8]}",
            "age": 28,
            "gender": "female",
            "village": "Wagholi",
            "phone": f"9{uuid.uuid4().int % 10**9:09d}",
            "pregnancy_stage": "7 months",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _record_visit(client, headers, worker_id, patient_id):
    audio = base64.b64encode(DEMO_TRANSCRIPT.encode()).decode()
    resp = client.post(
        "/api/v1/visits/voice",
        headers=headers,
        json={"worker_id": worker_id, "patient_id": patient_id,
              "audio_base64": audio, "language_code": "hi"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Correcting a patient's details ──────────────────────────────────────

def test_a_misheard_name_can_be_corrected_and_the_change_is_auditable():
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers, name="Meera Patil")

        resp = client.patch(
            f"/api/v1/patients/{meera['id']}",
            headers=headers,
            json={"name": "Meerabai Patil", "age": 29,
                  "reason": "Name and age were misheard at registration."},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Meerabai Patil"
        assert resp.json()["age"] == 29

        db = SessionLocal()
        try:
            entry = (
                db.query(AuditLog)
                .filter(AuditLog.action_type == "patient.correct",
                        AuditLog.record_id == meera["id"])
                .first()
            )
            assert entry is not None, "a correction with no audit trail is indistinguishable from tampering"
            assert "misheard" in entry.details
            # The old name must not be written into the audit log in clear:
            # that would undo the encryption on the row it describes.
            assert "Meera Patil" not in entry.details
            assert "age" in entry.details
        finally:
            db.close()


def test_a_correction_only_touches_the_fields_it_was_sent():
    """A client that knows about an age must not blank a phone it never sent."""
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers)
        db = SessionLocal()
        try:
            meera_phone = db.get(Patient, meera["id"]).phone
        finally:
            db.close()

        client.patch(f"/api/v1/patients/{meera['id']}", headers=headers,
                     json={"age": 31, "reason": "Corrected her age after checking her card."})

        db = SessionLocal()
        try:
            patient = db.get(Patient, meera["id"])
            assert patient.age == 31
            assert patient.phone == meera_phone, "an unsent field was overwritten"
            assert patient.pregnancy_stage == "7 months"
        finally:
            db.close()


def test_a_correction_with_nothing_different_is_refused():
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers)
        resp = client.patch(f"/api/v1/patients/{meera['id']}", headers=headers,
                            json={"name": meera["name"], "reason": "No change at all."})
        assert resp.status_code == 400


def test_a_correction_needs_a_reason():
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers)
        resp = client.patch(f"/api/v1/patients/{meera['id']}", headers=headers,
                            json={"age": 33})
        assert resp.status_code == 422


def test_a_bmo_may_read_a_patient_but_not_rewrite_her_details():
    """SRS table 4 gives a BMO read-only access to patient data. A district
    officer editing a detail she has no way to verify is a guess
    overwriting the only person who knows."""
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        meera = _patient(client, {"Authorization": f"Bearer {asha['access_token']}"})

        bmo = _login(client, "9999999902", "1234")
        resp = client.patch(
            f"/api/v1/patients/{meera['id']}",
            headers={"Authorization": f"Bearer {bmo['access_token']}"},
            json={"age": 40, "reason": "Trying to edit from the district office."},
        )
        assert resp.status_code == 403


# ── Closing a line in the register ──────────────────────────────────────

def test_closing_a_patient_cancels_her_pending_followups_and_hides_her_from_the_caseload():
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers)
        _record_visit(client, headers, asha["worker_id"], meera["id"])

        db = SessionLocal()
        try:
            pending = (
                db.query(Action).join(Visit, Action.visit_id == Visit.visit_id)
                .filter(Visit.patient_id == meera["id"], Action.type == "followup",
                        Action.status == "pending").count()
            )
            assert pending >= 1, "expected a pending follow-up to exist before closing"
        finally:
            db.close()

        resp = client.post(
            f"/api/v1/patients/{meera['id']}/status",
            headers=headers,
            json={"status": "moved", "reason": "Moved to her mother's village in another district."},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "moved"
        assert resp.json()["followups_cancelled"] >= 1
        assert resp.json()["closed_at"] is not None

        # Gone from the caseload...
        names = [p["name"] for p in client.get(
            f"/api/v1/patients/{asha['worker_id']}", headers=headers).json()["patients"]]
        assert meera["name"] not in names

        # ...but her history is untouched. A district's past figures must
        # not move because somebody changed address.
        db = SessionLocal()
        try:
            assert db.query(Visit).filter(Visit.patient_id == meera["id"]).count() >= 1
            assert db.query(Action).join(Visit, Action.visit_id == Visit.visit_id).filter(
                Visit.patient_id == meera["id"], Action.type == "followup",
                Action.status == "pending").count() == 0
        finally:
            db.close()


def test_a_closed_patient_can_be_reopened():
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers)

        client.post(f"/api/v1/patients/{meera['id']}/status", headers=headers,
                    json={"status": "inactive", "reason": "Closed by mistake, wrong row tapped."})
        resp = client.post(f"/api/v1/patients/{meera['id']}/status", headers=headers,
                           json={"status": "active", "reason": "Reopening, she never left."})
        assert resp.status_code == 200, resp.text
        assert resp.json()["closed_at"] is None

        names = [p["name"] for p in client.get(
            f"/api/v1/patients/{asha['worker_id']}", headers=headers).json()["patients"]]
        assert meera["name"] in names


def test_closing_to_the_status_she_already_has_is_refused():
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers)
        resp = client.post(f"/api/v1/patients/{meera['id']}/status", headers=headers,
                           json={"status": "active", "reason": "She is already active."})
        assert resp.status_code == 400


# ── Amending what a visit recorded ──────────────────────────────────────

def test_amending_a_misheard_bp_reclassifies_the_visit_and_withdraws_the_referral():
    """The case the endpoint exists for: the cuff read 120/80 and Bhashini
    heard 140/90. Overriding the label would leave the wrong number
    underneath it."""
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers)
        visit = _record_visit(client, headers, asha["worker_id"], meera["id"])
        assert visit["risk_level"] == "HIGH"

        resp = client.patch(
            f"/api/v1/visits/{visit['visit_id']}/record",
            headers=headers,
            json={"bp_systolic": 120, "bp_diastolic": 80,
                  "reason": "Cuff actually read 120/80; the recording mangled it."},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["previous_risk_level"] == "HIGH"
        assert body["new_risk_level"] != "HIGH"
        assert body["amended_fields"]["bp_systolic"] == {"from": 140, "to": 120}

        db = SessionLocal()
        try:
            v = db.get(Visit, visit["visit_id"])
            # The reading itself changed, not just the label.
            assert '"bp_systolic":120' in v.structured_json.replace(" ", "")
            assert v.risk_level != "HIGH"
            # The transcript is evidence of what was said and is never rewritten.
            assert "140" in v.transcript

            flag = db.query(RiskFlag).filter(RiskFlag.visit_id == visit["visit_id"]).one()
            assert flag.risk_level == v.risk_level
            assert "140/90" not in (flag.drivers_json or "")

            # The referral letter drafted for a HIGH visit is withdrawn.
            referral = db.query(Action).filter(
                Action.visit_id == visit["visit_id"], Action.type == "referral").first()
            assert referral is not None and referral.status == "cancelled"
        finally:
            db.close()


def test_an_amendment_supersedes_an_earlier_override():
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers)
        visit = _record_visit(client, headers, asha["worker_id"], meera["id"])

        client.post(f"/api/v1/visits/{visit['visit_id']}/risk-override", headers=headers,
                    json={"new_risk_level": "LOW", "reason": "Judged this one clinically fine."})

        resp = client.patch(f"/api/v1/visits/{visit['visit_id']}/record", headers=headers,
                            json={"bp_systolic": 118, "bp_diastolic": 76,
                                  "reason": "Re-read the cuff; it was 118/76."})
        assert resp.status_code == 200, resp.text
        assert resp.json()["override_cleared"] is True

        db = SessionLocal()
        try:
            flag = db.query(RiskFlag).filter(RiskFlag.visit_id == visit["visit_id"]).one()
            assert flag.overridden_by is None, (
                "a judgement about the old readings must not survive them being replaced"
            )
        finally:
            db.close()


def test_amending_another_workers_visit_is_refused():
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers)
        visit = _record_visit(client, headers, asha["worker_id"], meera["id"])

        bmo = _login(client, "9999999902", "1234")
        resp = client.patch(
            f"/api/v1/visits/{visit['visit_id']}/record",
            headers={"Authorization": f"Bearer {bmo['access_token']}"},
            json={"bp_systolic": 110, "bp_diastolic": 70,
                  "reason": "Amending a measurement from the district office."},
        )
        assert resp.status_code == 403, (
            "a BMO may override a judgement but not claim what a cuff showed"
        )


def test_an_amendment_that_changes_nothing_is_refused():
    with TestClient(app) as client:
        _seed()
        asha = _login(client)
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        meera = _patient(client, headers)
        visit = _record_visit(client, headers, asha["worker_id"], meera["id"])
        resp = client.patch(f"/api/v1/visits/{visit['visit_id']}/record", headers=headers,
                            json={"bp_systolic": 140, "reason": "Same value as before."})
        assert resp.status_code == 400
