"""FR-03.3: an ASHA (her own visits) or her ANM supervisor (visits within her
sub-centre) can override the AI's risk classification, but only with a
mandatory reason -- and the correction has to actually take effect
everywhere risk_level is read from (visit history, the escalation queue),
not just sit unused on the request/response."""
import base64

from fastapi.testclient import TestClient

from app.core.security import hash_pin
from app.db.models.audit_log import AuditLog
from app.db.models.worker import Worker
from app.db.session import SessionLocal
from app.main import app
from scripts.seed_synthetic_data import seed_demo_fixtures

DEMO_TRANSCRIPT = (
    "Meera Patil, 28 saal, 7 mahine ki pregnancy. Aaj BP 140 over 90 tha. "
    "Usne pichle 2 hafte se iron tablets nahi li. Pati bahar gaya hua hai."
)

OTHER_ASHA_PHONE = "9111111111"
OTHER_ASHA_SUB_CENTRE = "SC-TEST-OUTSIDE"


def _login(client: TestClient, phone: str, pin: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_other_asha(db) -> None:
    """A second ASHA in a sub-centre the demo ANM does NOT supervise, purely
    to prove cross-worker/cross-sub-centre overrides are rejected."""
    if db.query(Worker).filter(Worker.phone == OTHER_ASHA_PHONE).first():
        return
    db.add(
        Worker(
            name="Other Test ASHA",
            phone=OTHER_ASHA_PHONE,
            pin_hash=hash_pin("1234"),
            language_pref="hi",
            sub_centre_id=OTHER_ASHA_SUB_CENTRE,
            role="asha",
        )
    )
    db.commit()


def _seed():
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
        _seed_other_asha(db)
    finally:
        db.close()


def _record_demo_visit(client: TestClient, headers: dict, worker_id: str, patient_id: str) -> dict:
    audio_b64 = base64.b64encode(DEMO_TRANSCRIPT.encode()).decode()
    resp = client.post(
        "/api/v1/visits/voice",
        headers=headers,
        json={"worker_id": worker_id, "patient_id": patient_id, "audio_base64": audio_b64, "language_code": "hi"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_asha_can_override_her_own_visit_with_a_reason():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")

        visit = _record_demo_visit(client, headers, asha["worker_id"], meera["id"])
        assert visit["risk_level"] == "HIGH"

        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=headers,
            json={
                "new_risk_level": "medium",  # lowercase on purpose -- should be normalized
                "reason": "Re-checked her BP myself just now, it's back to a safe range.",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["previous_risk_level"] == "HIGH"
        assert body["new_risk_level"] == "MEDIUM"
        assert body["overridden_by"] == asha["worker_id"]
        assert body["overridden_by_name"] == "Sunita Sharma"
        assert body["overridden_by_role"] == "asha"

        # The correction -- and *who made it* -- is what shows up in her own
        # visit history from now on, not a vague "corrected by supervisor".
        history = client.get(f"/api/v1/workers/{asha['worker_id']}/history", headers=headers)
        entry = next(v for v in history.json()["visits"] if v["visit_id"] == visit["visit_id"])
        assert entry["risk_level"] == "MEDIUM"
        assert entry["risk_overridden"] is True
        assert "safe range" in entry["risk_override_reason"]
        assert entry["overridden_by_name"] == "Sunita Sharma"
        assert entry["overridden_by_role"] == "asha"

        # And a durable audit trail entry was written (not just the risk_flags row).
        db = SessionLocal()
        try:
            log = (
                db.query(AuditLog)
                .filter(AuditLog.record_id == visit["visit_id"], AuditLog.action_type == "risk.override")
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert log is not None
            assert log.user_id == asha["worker_id"]
            assert "safe range" in log.details
            assert "HIGH" in log.details
        finally:
            db.close()


def test_override_requires_a_real_reason():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")
        visit = _record_demo_visit(client, headers, asha["worker_id"], meera["id"])

        blank = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=headers,
            json={"new_risk_level": "LOW", "reason": "   "},
        )
        assert blank.status_code == 422

        too_short = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=headers,
            json={"new_risk_level": "LOW", "reason": "ok"},
        )
        assert too_short.status_code == 422


def test_override_rejects_unknown_risk_level():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")
        visit = _record_demo_visit(client, headers, asha["worker_id"], meera["id"])

        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=headers,
            json={"new_risk_level": "CRITICAL", "reason": "Made up risk level."},
        )
        assert resp.status_code == 422


def test_override_to_the_same_level_is_rejected():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")
        visit = _record_demo_visit(client, headers, asha["worker_id"], meera["id"])
        assert visit["risk_level"] == "HIGH"

        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=headers,
            json={"new_risk_level": "HIGH", "reason": "Agreeing with the AI changes nothing."},
        )
        assert resp.status_code == 400


def test_asha_cannot_override_another_workers_visit():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")
        visit = _record_demo_visit(client, headers, asha["worker_id"], meera["id"])

        other = _login(client, OTHER_ASHA_PHONE, "1234")
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=other_headers,
            json={"new_risk_level": "LOW", "reason": "Not my patient -- shouldn't be allowed."},
        )
        assert resp.status_code == 403


def test_anm_can_override_a_visit_in_her_sub_centre_and_it_drops_off_the_escalation_queue():
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        asha_headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=asha_headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")
        visit = _record_demo_visit(client, asha_headers, asha["worker_id"], meera["id"])
        assert visit["risk_level"] == "HIGH"

        anm = _login(client, "9999999901", "1234")  # Dr. Rekha Joshi, SC-PUNE-01 -- same sub-centre as Sunita
        anm_headers = {"Authorization": f"Bearer {anm['access_token']}"}

        pending_before = client.get("/api/v1/escalations/pending", headers=anm_headers)
        assert pending_before.status_code == 200
        ids_before = [e["visit_id"] for e in pending_before.json()["escalations"]]
        assert visit["visit_id"] in ids_before

        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=anm_headers,
            json={
                "new_risk_level": "LOW",
                "reason": "Called the patient directly -- the BP reading was a faulty cuff, retest was normal.",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["overridden_by"] == anm["worker_id"]
        assert resp.json()["overridden_by_name"] == "Dr. Rekha Joshi"
        assert resp.json()["overridden_by_role"] == "anm"

        pending_after = client.get("/api/v1/escalations/pending", headers=anm_headers)
        ids_after = [e["visit_id"] for e in pending_after.json()["escalations"]]
        assert visit["visit_id"] not in ids_after


def test_anm_cannot_override_a_visit_outside_her_sub_centre():
    with TestClient(app) as client:
        _seed()
        other = _login(client, OTHER_ASHA_PHONE, "1234")
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        other_patient = client.post(
            "/api/v1/patients",
            headers=other_headers,
            json={"name": "Outside Sub-Centre Patient", "age": 30, "gender": "female"},
        )
        assert other_patient.status_code == 201, other_patient.text
        visit = _record_demo_visit(client, other_headers, other["worker_id"], other_patient.json()["id"])

        anm = _login(client, "9999999901", "1234")  # SC-PUNE-01 -- not this patient's sub-centre
        anm_headers = {"Authorization": f"Bearer {anm['access_token']}"}
        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=anm_headers,
            json={"new_risk_level": "LOW", "reason": "Outside my sub-centre -- shouldn't be allowed."},
        )
        assert resp.status_code == 403


def test_bmo_can_override_any_visit_district_wide():
    """BMO oversight is district-wide (no sub-centre restriction, unlike an
    ANM) -- so a BMO can correct a visit belonging to any worker, anywhere."""
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        asha_headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=asha_headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")
        visit = _record_demo_visit(client, asha_headers, asha["worker_id"], meera["id"])

        bmo = _login(client, "9999999902", "1234")
        bmo_headers = {"Authorization": f"Bearer {bmo['access_token']}"}
        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=bmo_headers,
            json={"new_risk_level": "LOW", "reason": "District review call -- reading was inconsistent with the chart."},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["overridden_by_name"] == "Dr. Vikram Rao"
        assert resp.json()["overridden_by_role"] == "bmo"


def test_admin_cannot_override_risk():
    """Admin is system administration, not a clinical correction role --
    FR-03.3 is ASHA/ANM/BMO only."""
    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        asha_headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=asha_headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")
        visit = _record_demo_visit(client, asha_headers, asha["worker_id"], meera["id"])

        admin = _login(client, "9999999903", "1234")
        admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}
        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=admin_headers,
            json={"new_risk_level": "LOW", "reason": "Admin trying to override directly."},
        )
        assert resp.status_code == 403


def test_override_cascade_moves_followup_deadline_and_withdraws_stale_escalation():
    """Section 5 of the reliability review: a risk override has to touch more
    than the label. Downgrading a HIGH visit with an alert already in flight
    withdraws that alert, and either direction moves the follow-up deadline
    to match the new tier (still anchored to the visit, not to now)."""
    from datetime import timedelta

    from app.db.models.action import Action
    from app.db.models.notification import Notification
    from app.db.models.visit import Visit

    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")
        visit = _record_demo_visit(client, headers, asha["worker_id"], meera["id"])
        assert visit["risk_level"] == "HIGH"

        db = SessionLocal()
        try:
            # Simulate the state check_and_escalate would have produced after
            # 48h unactioned: an alert already queued for delivery.
            alert = Action(
                visit_id=visit["visit_id"], type="escalation_alert",
                content="ALERT: HIGH risk case overdue", status="pending",
            )
            db.add(alert)
            db.flush()
            db.add(Notification(action_id=alert.action_id, payload_json="{}",
                                 approved_by="system:escalation", status="queued"))
            db.commit()
            alert_id = alert.action_id

            followup_before = (
                db.query(Action)
                .filter(Action.visit_id == visit["visit_id"], Action.type == "followup")
                .first()
            )
            db_visit = db.get(Visit, visit["visit_id"])
            assert abs((followup_before.due_at - (db_visit.created_at + timedelta(days=2))).total_seconds()) < 1
        finally:
            db.close()

        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=headers,
            json={"new_risk_level": "LOW", "reason": "Rechecked myself, BP was normal on a second cuff."},
        )
        assert resp.status_code == 200, resp.text

        db = SessionLocal()
        try:
            followup_after = (
                db.query(Action)
                .filter(Action.visit_id == visit["visit_id"], Action.type == "followup")
                .first()
            )
            db_visit = db.get(Visit, visit["visit_id"])
            assert abs((followup_after.due_at - (db_visit.created_at + timedelta(days=30))).total_seconds()) < 1

            assert db.get(Action, alert_id).status == "cancelled"
            assert db.get(Notification, alert_id).status == "cancelled"
        finally:
            db.close()


def test_override_to_high_drafts_a_referral_if_none_exists():
    """FR-04.1: every HIGH visit gets a referral letter. Downgrading and then
    upgrading back to HIGH must not leave the visit with only a cancelled
    referral and no active one for the ASHA to send."""
    from app.db.models.action import Action

    with TestClient(app) as client:
        _seed()
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")
        visit = _record_demo_visit(client, headers, asha["worker_id"], meera["id"])
        assert visit["risk_level"] == "HIGH"

        client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=headers,
            json={"new_risk_level": "LOW", "reason": "Faulty cuff reading, retested normal at the time."},
        )

        resp = client.post(
            f"/api/v1/visits/{visit['visit_id']}/risk-override",
            headers=headers,
            json={"new_risk_level": "HIGH", "reason": "New information: she is now reporting severe headache."},
        )
        assert resp.status_code == 200, resp.text

        db = SessionLocal()
        try:
            referrals = (
                db.query(Action)
                .filter(Action.visit_id == visit["visit_id"], Action.type == "referral")
                .all()
            )
            active = [r for r in referrals if r.status != "cancelled"]
            assert len(active) == 1, [(r.status, r.content[:40]) for r in referrals]
            assert "severe headache" in active[0].content
        finally:
            db.close()
