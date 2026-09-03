import base64

from fastapi.testclient import TestClient

from app.main import app
from app.services.patient_intake import extract


def test_extracts_name_age_from_natural_phrasing():
    fields = extract("Sunita Devi, 32 saal, gaon Wagholi mein rehti hai, mobile number 98765 43210, female")
    assert fields.name == "Sunita Devi"
    assert fields.age == 32
    assert fields.village == "Wagholi"
    assert fields.phone == "9876543210"
    assert fields.gender == "female"


def test_extracts_name_via_naam_hai_fallback():
    fields = extract("naam Ramesh Kumar hai, umar 45 saal, male, village Shirur")
    assert fields.name == "Ramesh Kumar"
    assert fields.age == 45
    assert fields.gender == "male"
    assert fields.village == "Shirur"


def test_missing_fields_stay_none():
    fields = extract("this is just background noise with no real details")
    assert fields.name is None
    assert fields.age is None
    assert fields.phone is None


def _login(client: TestClient, phone: str, pin: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_voice_intake_endpoint_is_read_only_and_prefills():
    """Confirms the endpoint transcribes + extracts but never touches the
    patient roster -- the ASHA still has to call POST /api/v1/patients."""
    with TestClient(app) as client:
        asha = _login(client, "9999999999", "1234")
        headers = {"Authorization": f"Bearer {asha['access_token']}"}

        before = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        assert before.status_code == 200
        count_before = len(before.json()["patients"])

        transcript = "Kavita Sharma, 24 saal, gaon Hadapsar, phone number 9123456780, female"
        audio_b64 = base64.b64encode(transcript.encode()).decode()
        resp = client.post(
            "/api/v1/patients/voice-intake",
            headers=headers,
            json={"audio_base64": audio_b64, "language_code": "hi"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["transcript"] == transcript
        assert body["extracted"]["name"] == "Kavita Sharma"
        assert body["extracted"]["age"] == 24
        assert body["extracted"]["village"] == "Hadapsar"
        assert body["extracted"]["phone"] == "9123456780"
        assert body["extracted"]["gender"] == "female"

        after = client.get(f"/api/v1/patients/{asha['worker_id']}", headers=headers)
        assert len(after.json()["patients"]) == count_before  # nothing was created


def test_voice_intake_rejects_non_asha():
    with TestClient(app) as client:
        anm = _login(client, "9999999901", "1234")
        headers = {"Authorization": f"Bearer {anm['access_token']}"}
        audio_b64 = base64.b64encode(b"irrelevant").decode()
        resp = client.post(
            "/api/v1/patients/voice-intake",
            headers=headers,
            json={"audio_base64": audio_b64, "language_code": "hi"},
        )
        assert resp.status_code == 403
