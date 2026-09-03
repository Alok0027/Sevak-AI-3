"""End-to-end API smoke test: login -> patients -> voice visit -> dashboard.

Runs against the same DATABASE_URL as the dev server (sevakai_dev.db by
default -- see .env.example) since app/db/session.py binds its engine at
import time. Run `python -m scripts.seed_synthetic_data` once before pytest
if you want a completely clean assertion baseline; these tests only assert
properties that hold regardless of what else is in the database (idempotent
demo fixtures + relative counts), so they're safe to run against a
pre-seeded dev DB too.
"""
import base64

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from scripts.seed_synthetic_data import seed_demo_fixtures

DEMO_TRANSCRIPT = (
    "Meera Patil, 28 saal, 7 mahine ki pregnancy. Aaj BP 140 over 90 tha. "
    "Usne pichle 2 hafte se iron tablets nahi li. Pati bahar gaya hua hai."
)


def _login(client: TestClient, phone: str, pin: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_full_demo_flow():
    with TestClient(app) as client:
        db = SessionLocal()
        try:
            seed_demo_fixtures(db)
        finally:
            db.close()

        asha = _login(client, "9999999999", "1234")
        asha_headers = {"Authorization": f"Bearer {asha['access_token']}"}

        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=asha_headers)
        assert patients.status_code == 200
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
        body = visit.json()
        assert body["risk_level"] == "HIGH"
        assert any(a["type"] == "referral" for a in body["actions_generated"])
        assert any(a["type"] == "whatsapp" for a in body["actions_generated"])
        assert any(a["type"] == "followup" for a in body["actions_generated"])

        # An ASHA worker cannot see the district dashboard (RBAC, NFR-SC3).
        forbidden = client.get("/api/v1/dashboard/metrics", headers=asha_headers)
        assert forbidden.status_code == 403

        anm = _login(client, "9999999901", "1234")
        anm_headers = {"Authorization": f"Bearer {anm['access_token']}"}
        metrics = client.get("/api/v1/dashboard/metrics", headers=anm_headers)
        assert metrics.status_code == 200
        assert metrics.json()["high_risk_cases"] >= 1

        escalations = client.get("/api/v1/escalations/pending", headers=anm_headers)
        assert escalations.status_code == 200


def test_login_rejects_wrong_pin():
    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/login", json={"phone": "9999999999", "pin": "0000"})
        assert resp.status_code == 401


def test_unauthenticated_request_rejected():
    with TestClient(app) as client:
        resp = client.get("/api/v1/patients/anything")
        assert resp.status_code in (401, 403)
