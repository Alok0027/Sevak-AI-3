"""FR-01.4: transcribe-then-review-then-confirm flow for visit recording."""
import base64

from fastapi.testclient import TestClient

from app.main import app

DEMO_TRANSCRIPT = (
    "Meera Patil, 28 saal, 7 mahine ki pregnancy. Aaj BP 140 over 90 tha. "
    "Usne pichle 2 hafte se iron tablets nahi li. Pati bahar gaya hua hai."
)


def _login(client: TestClient, phone: str, pin: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_transcribe_endpoint_is_read_only():
    """Transcribing alone must never create a visit or run risk scoring."""
    with TestClient(app) as client:
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}

        history_before = client.get(f"/api/v1/workers/{asha['worker_id']}/history", headers=headers)
        visits_before = history_before.json()["worker"]["total_visits"]

        audio_b64 = base64.b64encode(DEMO_TRANSCRIPT.encode()).decode()
        resp = client.post(
            "/api/v1/visits/transcribe",
            headers=headers,
            json={"audio_base64": audio_b64, "language_code": "hi"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["transcript"] == DEMO_TRANSCRIPT

        history_after = client.get(f"/api/v1/workers/{asha['worker_id']}/history", headers=headers)
        assert history_after.json()["worker"]["total_visits"] == visits_before


def test_confirmed_transcript_is_used_verbatim_not_retranscribed():
    """The whole point of the review step: whatever the ASHA edits the
    transcript to must be exactly what feeds extraction/risk scoring --
    even though it differs from what a fresh transcription would produce."""
    with TestClient(app) as client:
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}

        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")

        edited_transcript = (
            "Meera Patil, 28 saal. BP 160 over 100 tha, bahut zyada high. "
            "Emergency jaisi situation hai."
        )
        visit = client.post(
            "/api/v1/visits/voice",
            headers=headers,
            json={
                "worker_id": asha["worker_id"],
                "patient_id": meera["id"],
                "confirmed_transcript": edited_transcript,
                "language_code": "hi",
            },
        )
        assert visit.status_code == 200, visit.text
        body = visit.json()
        assert body["transcript"] == edited_transcript
        assert body["extracted"]["bp_systolic"] == 160
        assert body["extracted"]["bp_diastolic"] == 100
        assert body["risk_level"] == "HIGH"


def test_voice_endpoint_requires_audio_or_transcript():
    with TestClient(app) as client:
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}
        patients = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        meera = next(p for p in patients.json()["patients"] if p["name"] == "Meera Patil")

        resp = client.post(
            "/api/v1/visits/voice",
            headers=headers,
            json={"worker_id": asha["worker_id"], "patient_id": meera["id"], "language_code": "hi"},
        )
        assert resp.status_code == 422
